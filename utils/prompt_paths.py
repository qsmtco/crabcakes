# utils/prompt_paths.py
# Path resolvers for the per-project prompts library.
#
# Architecture: pure Python, no GTK, no I/O beyond os.path.
# Consumed by ui/handlers/prompts_handler.py and utils/prompts.py so the
# resolution logic lives in ONE place (SPEC-PROJECT-PROMPTS-DIRECTORY §2.2).

import os


def _get_app_root() -> str:
    """Return the app install dir (crabcakes project root)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_USER_PROMPTS_DIR: str = os.path.join(_get_app_root(), "prompts")

# Subdirectories of <app>/prompts/ that are APP-LEVEL (NOT seeded per project).
# system/ = agent personality templates consumed by utils/prompt_loader.py.
# claude-code-clean/ = third-party human reference material.
APP_LEVEL_PROMPTS_SUBDIRS: frozenset[str] = frozenset({"system", "claude-code-clean"})


def get_project_prompts_dir(project_path: str | None) -> str:
    """Return the per-project prompts directory, or app-level fallback.

    Resolution order (SPEC §2.2):
      1. project_path is None or empty string -> APP_USER_PROMPTS_DIR
      2. <project>/.crabcakes/prompts/ exists -> return it
      3. otherwise -> APP_USER_PROMPTS_DIR (unseeded project / legacy state)

    Never raises: falls back to APP_USER_PROMPTS_DIR on any OSError from
    os.path.isdir.
    """
    if not project_path:
        return APP_USER_PROMPTS_DIR
    proj = os.path.join(project_path, ".crabcakes", "prompts")
    try:
        if os.path.isdir(proj):
            return proj
    except OSError:
        pass
    return APP_USER_PROMPTS_DIR


def ensure_project_prompts_dir(project_path: str | None) -> str:
    """Return the prompts directory to WRITE into, creating the project's
    dir if needed.

    Write-side counterpart of get_project_prompts_dir(): unlike reads, a
    write into an unseeded project must CREATE <project>/.crabcakes/prompts/
    rather than silently falling back to the app dir (the read-side fallback
    would route the user's prompt into the app library — SPEC-PROJECT-PROMPTS-
    DIRECTORY §2.7b, Debugger Phase 3 audit BUG #1).

    project_path None/empty -> APP_USER_PROMPTS_DIR (never created here).

    Never raises: if makedirs fails, the project path is still returned so
    the caller's write fails loudly with a clear errno instead of silently
    polluting the app dir.
    """
    if not project_path:
        return APP_USER_PROMPTS_DIR
    proj = os.path.join(project_path, ".crabcakes", "prompts")
    try:
        os.makedirs(proj, exist_ok=True)
    except (OSError, ValueError):
        # OSError: unwritable/unusable parent (e.g. .crabcakes is a file).
        # ValueError: malformed path such as an embedded NUL byte — the read
        # resolver is graceful on these (os.path.isdir swallows ValueError),
        # so the write resolver must not raise either; returning proj makes
        # the CALLER's write fail loudly with the exact bad path instead of
        # silently polluting the app dir.
        pass
    return proj
