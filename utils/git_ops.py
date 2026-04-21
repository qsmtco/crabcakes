# utils/git_ops.py
# GitPython wrapper for all git operations.
# Returns structured GitResult objects. Never raises unhandled exceptions.
#
# New dependency: gitpython (pip install gitpython).
# Import: import git (as gitpython to avoid shadowing the module name).

import git as gitpython
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitResult:
    """Result of a git operation."""
    success: bool
    stdout: str          # textual output (diff, log, status)
    error: str           # error message if success=False
    sha: Optional[str] = None  # commit SHA when applicable


def is_repo(project_path: str) -> bool:
    """True if project_path contains a valid git repository."""
    try:
        gitpython.Repo(project_path)
        return True
    except Exception:
        return False


def init_repo(project_path: str) -> GitResult:
    """Initialize a git repo if not already one."""
    try:
        gitpython.Repo.init(project_path)
        return GitResult(success=True, stdout="", error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def get_head_sha(project_path: str) -> GitResult:
    """Get current HEAD commit SHA."""
    try:
        repo = gitpython.Repo(project_path)
        if repo.head.is_detached:
            sha = repo.head.commit.hexsha
        else:
            sha = repo.head.commit.hexsha
        return GitResult(success=True, stdout=sha, error="", sha=sha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def stage_all(project_path: str) -> GitResult:
    """Stage all changes (equivalent to git add -A)."""
    try:
        repo = gitpython.Repo(project_path)
        # Use git add -A via the git command to stage everything
        repo.git.add("-A")
        return GitResult(success=True, stdout="", error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def commit(project_path: str, message: str) -> GitResult:
    """Commit staged changes. Returns SHA in result.sha."""
    try:
        repo = gitpython.Repo(project_path)
        commit_obj = repo.index.commit(message)
        return GitResult(success=True, stdout=str(commit_obj.hexsha), error="", sha=commit_obj.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def diff_against(project_path: str, sha: str) -> GitResult:
    """Full unified diff of commit sha vs current HEAD commit.
    Shows what changed between the checkpoint (sha) and now (HEAD)."""
    try:
        repo = gitpython.Repo(project_path)
        diff_text = repo.git.diff(sha, "HEAD")
        return GitResult(success=True, stdout=diff_text, error="", sha=repo.head.commit.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def diff_stat_against(project_path: str, sha: str) -> GitResult:
    """Stat summary of diff (--stat output) between sha and HEAD."""
    try:
        repo = gitpython.Repo(project_path)
        stat_text = repo.git.diff(sha, "HEAD", "--stat")
        return GitResult(success=True, stdout=stat_text, error="", sha=repo.head.commit.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def diff_file_against(project_path: str, sha: str, file_path: str) -> GitResult:
    """Diff for a single file between commit sha and HEAD."""
    try:
        repo = gitpython.Repo(project_path)
        diff_text = repo.git.diff(sha, "HEAD", "--", file_path)
        return GitResult(success=True, stdout=diff_text, error="", sha=repo.head.commit.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def checkout_paths(project_path: str, sha: str, paths: list[str]) -> GitResult:
    """Revert file(s) to their state at sha. Equivalent to git checkout <sha> -- <paths>."""
    try:
        repo = gitpython.Repo(project_path)
        repo.git.checkout(sha, "--", *paths)
        return GitResult(success=True, stdout="", error="", sha=sha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def log(project_path: str, count: int = 10) -> GitResult:
    """Recent commit log as text."""
    try:
        repo = gitpython.Repo(project_path)
        log_text = repo.git.log(f"-{count}", "--oneline", "--all")
        return GitResult(success=True, stdout=log_text, error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def push(project_path: str, remote: str = "origin", branch: str = "main") -> GitResult:
    """Push to remote."""
    try:
        repo = gitpython.Repo(project_path)
        origin = repo.remote(remote)
        info = origin.push(refspec=f"HEAD:{branch}")
        # Check if push succeeded
        push_info = info[0]
        if push_info.flags & push_info.ERROR:
            return GitResult(success=False, stdout="", error=f"Push rejected: {push_info.summary}", sha=None)
        return GitResult(success=True, stdout=push_info.summary, error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def status(project_path: str) -> GitResult:
    """git status --porcelain output."""
    try:
        repo = gitpython.Repo(project_path)
        status_text = repo.git.status("--porcelain")
        return GitResult(success=True, stdout=status_text, error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)
