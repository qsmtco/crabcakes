# utils/git_ops.py
# GitPython wrapper for all git operations.
# Returns structured GitResult objects. Never raises unhandled exceptions.
#
# New dependency: gitpython (pip install gitpython).
# Import: import git (as gitpython to avoid shadowing the module name).

import re
import git as gitpython
from dataclasses import dataclass
from typing import Optional


# MED-11: Validate git commit SHA to prevent argument injection
_VALID_SHA_RE = re.compile(r"^(HEAD|[0-9a-fA-F]{4,40})$")


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


def get_branch(project_path: str) -> GitResult:
    """Get current git branch name. Returns 'HEAD detached' if detached."""
    try:
        repo = gitpython.Repo(project_path)
        if repo.head.is_detached:
            return GitResult(success=True, stdout="(detached HEAD)", error="")
        return GitResult(success=True, stdout=repo.active_branch.name, error="")
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e))


def stage_all(project_path: str) -> GitResult:
    """Stage all changes (equivalent to git add -A)."""
    try:
        repo = gitpython.Repo(project_path)
        # Use git add -A via the git command to stage everything
        repo.git.add("-A")
        return GitResult(success=True, stdout="", error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)


def commit(project_path: str, message: str, allow_empty: bool = False) -> GitResult:
    """Commit staged changes. Returns SHA in result.sha.

    Args:
        project_path: Path to the git repository.
        message: Commit message.
        allow_empty: If True, allow empty commits (no staged changes). Use only
            for checkpoint markers where the SHA itself is the desired output.
            Default is False — refuse to create empty commits, since they
            pollute the git log with the captain's signature on nothing.

    Returns:
        GitResult. If allow_empty is False and the working tree is clean,
        returns success=False with error="nothing to commit (working tree clean)".
    """
    try:
        repo = gitpython.Repo(project_path)
        # Empty-check: refuse to commit if there's nothing staged (unless caller
        # explicitly allows it via allow_empty=True).
        # On a fresh repo with no commits, HEAD doesn't resolve — treat that as
        # "has changes" since the first commit is always valid.
        if not allow_empty:
            try:
                has_staged = bool(repo.index.diff("HEAD"))
            except Exception:
                # HEAD doesn't resolve (no commits yet) — allow the commit
                has_staged = True
            if not has_staged:
                return GitResult(
                    success=False, stdout="", error="nothing to commit (working tree clean)",
                    sha=None,
                )
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
    """Revert file(s) to their state at sha. Equivalent to git checkout <sha> -- <paths>.

    MED-11: Validates sha before passing to git to prevent argument injection.
    """
    # MED-11: Validate SHA before git call
    if sha != "HEAD" and not _VALID_SHA_RE.match(sha):
        return GitResult(success=False, stdout="", error=f"Invalid git ref: {sha}", sha=None)
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


def get_recent_commits(project_path: str, count: int = 10) -> GitResult:
    """
    Recent commits as lines of "sha message" (one line per commit, no decorations).
    Used by FeedHandler to seed the project feed on open.

    Returns GitResult where stdout is lines of: "<sha> <commit subject>"
    """
    try:
        repo = gitpython.Repo(project_path)
        lines = []
        for commit in repo.iter_commits(max_count=count):
            sha = commit.hexsha[:8]
            # First line of commit message only (subject)
            subject = commit.message.split("\n", 1)[0]
            lines.append(f"{sha} {subject}")
        return GitResult(success=True, stdout="\n".join(lines), error="", sha=None)
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


def diff_working_tree(project_path: str, file_path: str | None = None) -> GitResult:
    """Diff of working tree against HEAD (unstaged + staged changes).

    Equivalent to: git diff HEAD -- [file_path]
    If file_path is None, diffs all files.
    """
    try:
        repo = gitpython.Repo(project_path)
        args = ["HEAD"]
        if file_path:
            args.extend(["--", file_path])
        diff_text = repo.git.diff(*args)
        return GitResult(success=True, stdout=diff_text, error="", sha=None)
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
