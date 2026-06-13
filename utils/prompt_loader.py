# utils/prompt_loader.py
# Load, template-fill, and compose system prompts from prompts/system/.
#
# Pure Python — no GTK, no network. Thread-safe (pure functions, no state).
#
# Public API:
#   load_prompt_template(name) -> str | None
#   fill_template(template, variables) -> str
#   compose_system_prompt(agent_name, project_path, ...) -> str
#
# Token budget note:
#   The composed system prompt for Coder (all templates + tool descriptions) is
#   approximately 14K chars / ~3.5K tokens. Tool descriptions alone are ~3.8K chars.
#   For a 128K context model this is negligible (<3%). For smaller models, monitor.
#   Set CRABCAKES_PROMPT_DEBUG=1 to dump the full composed prompt to stdout.

import os
import logging
import re

_logger = logging.getLogger(__name__)

SYSTEM_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "system")

# Pattern: {{VARIABLE_NAME}}
_VAR_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def load_prompt_template(name: str) -> str | None:
    """Load a prompt template from prompts/system/<name>.md.

    Returns raw template string with {{VARIABLES}} intact, or None if not found.
    """
    path = os.path.join(SYSTEM_DIR, f"{name}.md")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        return content if content else None
    except OSError as e:
        _logger.warning("Failed to load prompt template %s: %s", name, e)
        return None


def fill_template(template: str, variables: dict[str, str]) -> str:
    """Replace {{KEY}} with values from variables dict.

    Resolved variables are replaced. Unresolved variables are stripped entirely
    and logged at WARNING level to aid debugging.
    """
    unresolved: list[str] = []

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            return variables[key]
        unresolved.append(key)
        return ""  # strip unresolved

    result = _VAR_RE.sub(_replace, template)
    if unresolved:
        _logger.warning("Unresolved template variables stripped: %s", ", ".join(unresolved))
    return result


def _load_project_context_file(project_path: str, filename: str, max_size: int = 10_000) -> str | None:
    """Load a per-project context file from .crabcakes/ directory.

    Args:
        project_path: Absolute path to the project root.
        filename: Name of the file in .crabcakes/ (e.g. "coder-bugs.md").
        max_size: Maximum file size in bytes. Skip larger files.

    Returns:
        File content as string, or None if file doesn't exist / too large / unreadable.
    """
    filepath = os.path.join(project_path, ".crabcakes", filename)
    if not os.path.isfile(filepath):
        return None
    try:
        size = os.path.getsize(filepath)
        if size > max_size:
            _logger.warning(
                "Project context file %s is too large (%d bytes, max %d) — skipping",
                filename, size, max_size,
            )
            return None
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        return content if content else None
    except OSError as e:
        _logger.debug("Failed to read project context file %s: %s", filename, e)
        return None


def _get_agent_self_improvement_config(agent_role: str) -> dict:
    """Get the self_improvement config for an agent from its YAML definition.

    Delegates to utils.agent_defs for the base defaults, then merges
    with the agent's YAML-defined overrides.
    """
    from utils.agent_defs import load_agent_def_by_role, get_default_si_config
    try:
        agent_def = load_agent_def_by_role(agent_role)
        if agent_def:
            can_write = "write_file" in agent_def.get("tools", [])
            defaults = get_default_si_config(can_write=can_write)
            config = agent_def.get("self_improvement", {})
            return {**defaults, **config}
    except Exception:
        pass
    # Fallback — safe defaults
    return get_default_si_config(can_write=False)


def compose_system_prompt(
    agent_name: str = "",
    agent_role: str = "",
    project_path: str | None = None,
    project_awareness: dict | None = None,
    tools: list[str] | None = None,
    review_mode: str = "off",
) -> str:
    """Compose the full system prompt by loading and merging templates.

    Selection logic:
    1. Always: default.md
    2. If project active: project-awareness.md (filled with awareness variables)
    3. If review_mode != "off": code-review.md
    4. If agent_role == "coder": coder.md
    5. If agent_role == "debugger": debugger.md
    6. If project active + agent_role: {role}-bugs.md, {role}-rules.md (self-improvement)

    Templates are concatenated with double-newline separators.
    Missing templates are silently skipped.
    After composition, all variables are filled from project_awareness + built-in vars.

    Args:
        agent_name: Display name of the agent.
        agent_role: Explicit role identifier ("coder", "debugger", or "" for gateway agents).
        project_path: Absolute path to the project root, or None.
        project_awareness: Dict of template variables from build_awareness_dict().
        tools: List of tool names (for agent runtime).
        review_mode: "off" | "review".

    Returns:
        Composed and filled system prompt string.
    """
    awareness = project_awareness or {}
    parts: list[str] = []

    # 1. Always load default
    default = load_prompt_template("default")
    if default:
        parts.append(default)

    # 1b. Collaboration protocol (all agents — applies regardless of project/role)
    collab = load_prompt_template("collab")
    if collab:
        parts.append(collab)

    # 1c. CrabCakes platform context (all agents — applies regardless of project/role)
    cc_ctx = load_prompt_template("crabcakes-context")
    if cc_ctx:
        parts.append(cc_ctx)

    # 2. Project awareness (when project active)
    if project_path:
        pa = load_prompt_template("project-awareness")
        if pa:
            parts.append(pa)

    # 3. CrabCakes commands reference (when project active)
    if project_path:
        cmds = load_prompt_template("crabcakes-commands")
        if cmds:
            parts.append(cmds)

    # 4. Project onboarding (when project active but not yet onboarded)
    if project_path:
        try:
            from utils.project_awareness import is_project_onboarded
            if agent_role == "coder" and not is_project_onboarded(project_path):
                onboarding = load_prompt_template("project-onboarding")
                if onboarding:
                    parts.append(onboarding)
        except Exception:
            pass  # non-fatal — skip onboarding if check fails

    # 5. Code review mode
    if review_mode and review_mode != "off":
        cr = load_prompt_template("code-review")
        if cr:
            parts.append(cr)

    # 6. Agent-specific templates (by explicit role)
    if agent_role == "coder":
        ct = load_prompt_template("coder")
        if ct:
            parts.append(ct)
    elif agent_role == "debugger":
        dt = load_prompt_template("debugger")
        if dt:
            parts.append(dt)
    elif agent_role == "helper":
        ct = load_prompt_template("auxilium")
        if ct:
            parts.append(ct)

    # 7. Per-agent self-improvement context files (bug journal + project rules)
    if project_path and agent_role:
        si_config = _get_agent_self_improvement_config(agent_role)

        if si_config.get("bug_journal", True):
            bugs_file = f"{agent_role}-bugs.md"
            bug_journal = _load_project_context_file(project_path, bugs_file)
            if bug_journal:
                parts.append(bug_journal)

        if si_config.get("project_rules", True):
            rules_file = f"{agent_role}-rules.md"
            project_rules = _load_project_context_file(project_path, rules_file)
            if project_rules:
                parts.append(project_rules)

    if not parts:
        _logger.warning("No system prompt templates found in %s", SYSTEM_DIR)
        return ""

    composed = "\n\n".join(parts)

    # Build variable dict
    if tools:
        tool_list_str = "## Tools\n" + "\n".join(f"  - {t}" for t in tools)
    else:
        tool_list_str = ""  # Gateway agents — tool info controlled by gateway, not CrabCakes

    # Agent type identity — derived from role so each agent knows what it is
    if agent_role:
        agent_type = "special agent"
        agent_type_desc = "You run locally against LLM APIs with direct access to file/exec tools."
    else:
        agent_type = "gateway agent"
        agent_type_desc = "You run through the OpenClaw gateway."

    variables = {
        "AGENT_NAME": agent_name or "",
        "AGENT_TYPE": agent_type,
        "AGENT_TYPE_DESC": agent_type_desc,
        "PROJECT_PATH": project_path or "(no project open)",
        "PROJECT_NAME": awareness.get("PROJECT_NAME", ""),
        "TEAM_ROSTER": awareness.get("TEAM_ROSTER", ""),
        "CURRENT_STATE": awareness.get("CURRENT_STATE", ""),
        "PROJECT_MEMORY": awareness.get("PROJECT_MEMORY", ""),
        "WORKFLOW_STATUS": awareness.get("WORKFLOW_STATUS", ""),
        "REVIEW_MODE": review_mode,
        "TOOL_LIST": tool_list_str,
    }

    result = fill_template(composed, variables)

    # Append file context if project active (outside templates — large dynamic content)
    if project_path:
        from agent.context import build_file_context
        file_context = build_file_context(project_path)
        if file_context:
            result += f"\n\n## File context\n\n{file_context}"

    # Debug dump — set CRABCAKES_PROMPT_DEBUG=1 to inspect the full composed prompt
    if os.environ.get("CRABCAKES_PROMPT_DEBUG"):
        import sys
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"COMPOSED PROMPT ({len(result)} chars / ~{len(result)//4} tokens)", file=sys.stderr)
        print(f"Agent: {agent_name} | Role: {agent_role}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        print(result, file=sys.stderr)
        print(f"\n{'='*60}\n", file=sys.stderr)

    return result
