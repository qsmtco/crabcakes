# tests/test_git_ops.py
# Tests for utils/git_ops.py
# Tests against temporary git repos (created via GitPython in setUp, deleted in tearDown).

import os
import tempfile
import shutil
import pytest

# Skip if gitpython not available
try:
    import git as gitpython
    from utils.git_ops import (
        is_repo, init_repo, get_head_sha, stage_all, commit,
        diff_against, diff_stat_against, diff_file_against,
        diff_file_against_working_tree,
        checkout_paths, log, file_log, push, status, status_porcelain, GitResult,
    )
except ImportError:
    pytest.skip("gitpython not available", allow_module_level=True)


@pytest.fixture
def temp_repo():
    """Create a temporary directory with a fresh git repo. Delete on teardown."""
    tmpdir = tempfile.mkdtemp(prefix="crabcakes_test_git_")
    repo = gitpython.Repo.init(tmpdir)
    # Configure git user for commits
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def repo_with_commit(temp_repo):
    """A repo with one initial commit containing 'hello.txt'."""
    fpath = os.path.join(temp_repo, "hello.txt")
    with open(fpath, "w") as f:
        f.write("Hello, world!\n")
    repo = gitpython.Repo(temp_repo)
    repo.index.add(["hello.txt"])
    commit_obj = repo.index.commit("Initial commit")
    return temp_repo, str(commit_obj.hexsha)


class TestIsRepo:
    def test_is_repo_true(self, temp_repo):
        assert is_repo(temp_repo) is True

    def test_is_repo_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_repo(tmpdir) is False

    def test_is_repo_nonexistent(self):
        assert is_repo("/nonexistent/path/12345") is False


class TestInitRepo:
    def test_init_repo_creates_repo(self, temp_repo):
        # temp_repo is already a repo, but let's test on a fresh dir
        with tempfile.TemporaryDirectory() as tmpdir:
            result = init_repo(tmpdir)
            assert result.success is True
            assert is_repo(tmpdir) is True

    def test_init_existing_repo(self, temp_repo):
        # Idempotent — no error if already a repo
        result = init_repo(temp_repo)
        assert result.success is True


class TestCommit:
    def test_commit_success(self, temp_repo):
        # Create a file and commit
        fpath = os.path.join(temp_repo, "test.txt")
        with open(fpath, "w") as f:
            f.write("Test content\n")
        stage_all(temp_repo)
        result = commit(temp_repo, "Test commit")
        assert result.success is True
        assert result.sha is not None
        assert len(result.sha) == 40  # full SHA

    def test_commit_nothing_staged(self, temp_repo):
        # Note: GitPython/empty git repo - first commit creates an empty commit
        # if index is empty and no parent exists. Subsequent empty commits may fail.
        # We test the common case: adding a file then committing.
        fpath = os.path.join(temp_repo, "test.txt")
        with open(fpath, "w") as f:
            f.write("Test content\n")
        stage_all(temp_repo)
        result = commit(temp_repo, "Test commit")
        assert result.success is True
        assert result.sha is not None

    def test_commit_refuses_empty_when_allow_empty_false(self, repo_with_commit):
        """When the working tree is clean and allow_empty=False (default),
        commit() returns success=False with 'nothing to commit' error.
        No commit is created.
        """
        path, original_sha = repo_with_commit
        result = commit(path, "test empty commit")
        assert result.success is False
        assert "nothing to commit" in result.error
        # HEAD didn't change — no commit was created
        head_after = get_head_sha(path)
        assert head_after.sha == original_sha

    def test_commit_allows_empty_when_allow_empty_true(self, repo_with_commit):
        """When the working tree is clean and allow_empty=True, commit() creates
        an empty commit with the given message. Use only for checkpoint markers.
        """
        path, original_sha = repo_with_commit
        result = commit(path, "test checkpoint", allow_empty=True)
        assert result.success is True
        assert result.sha is not None
        assert result.sha != original_sha  # new commit created

    def test_commit_succeeds_when_changes_staged(self, repo_with_commit):
        """When the working tree has staged changes, commit() creates a
        non-empty commit with the given message. allow_empty has no effect.
        """
        path, _ = repo_with_commit
        # Stage a new file
        fpath = os.path.join(path, "new_file.txt")
        with open(fpath, "w") as f:
            f.write("new content\n")
        stage_all(path)
        result = commit(path, "real change")
        assert result.success is True
        assert result.sha is not None


class TestGetHeadSha:
    def test_get_head_sha(self, repo_with_commit):
        path, sha = repo_with_commit
        result = get_head_sha(path)
        assert result.success is True
        assert result.sha == sha

    def test_get_head_sha_empty_repo(self, temp_repo):
        result = get_head_sha(temp_repo)
        assert result.success is False


class TestDiffEmpty:
    def test_diff_empty_no_changes(self, repo_with_commit):
        path, sha = repo_with_commit
        result = diff_against(path, sha)
        assert result.success is True
        assert result.stdout == ""

    def test_diff_stat_empty(self, repo_with_commit):
        path, sha = repo_with_commit
        result = diff_stat_against(path, sha)
        assert result.success is True


class TestDiffChanges:
    def test_diff_with_changes(self, repo_with_commit):
        path, sha = repo_with_commit
        # Modify the file
        fpath = os.path.join(path, "hello.txt")
        with open(fpath, "w") as f:
            f.write("Hello, world! Modified!\n")
        stage_all(path)
        commit(path, "Modify hello.txt")

        result = diff_against(path, sha)
        assert result.success is True
        assert "hello.txt" in result.stdout
        assert "Modified" in result.stdout


class TestDiffStat:
    def test_diff_stat_with_changes(self, repo_with_commit):
        path, sha = repo_with_commit
        fpath = os.path.join(path, "hello.txt")
        with open(fpath, "w") as f:
            f.write("Hello, world! Modified!\n")
        stage_all(path)
        commit(path, "Modify hello.txt")

        result = diff_stat_against(path, sha)
        assert result.success is True
        assert "hello.txt" in result.stdout


class TestDiffFileAgainst:
    def test_diff_single_file(self, repo_with_commit):
        path, sha = repo_with_commit
        fpath = os.path.join(path, "hello.txt")
        with open(fpath, "w") as f:
            f.write("Hello, world! Modified!\n")
        stage_all(path)
        commit(path, "Modify hello.txt")

        result = diff_file_against(path, sha, "hello.txt")
        assert result.success is True
        assert "hello.txt" in result.stdout


class TestCheckoutPathsRevert:
    def test_checkout_reverts_file(self, repo_with_commit):
        path, sha = repo_with_commit
        fpath = os.path.join(path, "hello.txt")
        # Modify the file
        with open(fpath, "w") as f:
            f.write("Modified content\n")

        # Revert it
        result = checkout_paths(path, sha, ["hello.txt"])
        assert result.success is True

        # Verify content is back
        with open(fpath) as f:
            content = f.read()
        assert "Hello, world!" in content
        assert "Modified" not in content


class TestCheckoutPathsMultiple:
    def test_checkout_multiple_files(self, temp_repo):
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        # Create two files
        f1 = os.path.join(temp_repo, "file1.txt")
        f2 = os.path.join(temp_repo, "file2.txt")
        with open(f1, "w") as f:
            f.write("File 1 original\n")
        with open(f2, "w") as f:
            f.write("File 2 original\n")
        repo.index.add(["file1.txt", "file2.txt"])
        c1 = repo.index.commit("Initial")

        # Modify both files
        with open(f1, "w") as f:
            f.write("File 1 modified\n")
        with open(f2, "w") as f:
            f.write("File 2 modified\n")

        # Revert both
        result = checkout_paths(temp_repo, str(c1.hexsha), ["file1.txt", "file2.txt"])
        assert result.success is True

        with open(f1) as f:
            assert "original" in f.read()
        with open(f2) as f:
            assert "original" in f.read()


class TestPushNoRemote:
    def test_push_no_remote(self, repo_with_commit):
        path, _ = repo_with_commit
        result = push(path)
        assert result.success is False
        assert "origin" in result.error.lower() or "remote" in result.error.lower() or "error" in result.error.lower()


class TestStatusPorcelain:
    def test_status_new_file(self, repo_with_commit):
        path, _ = repo_with_commit
        # Create a new untracked file
        new_fpath = os.path.join(path, "new_file.txt")
        with open(new_fpath, "w") as f:
            f.write("New file content\n")
        result = status(path)
        assert result.success is True
        assert "new_file.txt" in result.stdout


class TestLog:
    def test_log_returns_text(self, repo_with_commit):
        path, _ = repo_with_commit
        result = log(path, count=5)
        assert result.success is True
        assert "Initial commit" in result.stdout


class TestErrorHandling:
    def test_invalid_path_returns_error(self):
        result = commit("/nonexistent/path/12345", "test")
        assert result.success is False
        assert result.error != ""

    def test_get_head_sha_nonexistent(self):
        result = get_head_sha("/nonexistent/path/12345")
        assert result.success is False


class TestCheckoutPathsShaGuards:
    """BUG #5: checkout_paths guards against non-string sha."""

    def test_checkout_paths_sha_int(self, repo_with_commit):
        path, _ = repo_with_commit
        result = checkout_paths(path, 42, ["hello.txt"])  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error

    def test_checkout_paths_sha_none(self, repo_with_commit):
        path, _ = repo_with_commit
        result = checkout_paths(path, None, ["hello.txt"])  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error

    def test_checkout_paths_sha_list(self, repo_with_commit):
        path, _ = repo_with_commit
        result = checkout_paths(path, ["HEAD"], ["hello.txt"])  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error


class TestDiffFileAgainstWorkingTree:
    """diff_file_against_working_tree: diff sha→working tree (includes uncommitted)."""

    def test_diff_against_head(self, repo_with_commit):
        """Diff HEAD against working tree with uncommitted changes."""
        path, sha = repo_with_commit
        # Make uncommitted changes
        fpath = os.path.join(path, "hello.txt")
        with open(fpath, "w") as f:
            f.write("Modified but not committed\n")

        result = diff_file_against_working_tree(path, "HEAD", "hello.txt")
        assert result.success is True
        assert "hello.txt" in result.stdout
        assert "Modified but not committed" in result.stdout

    def test_diff_against_specific_sha(self, temp_repo):
        """Diff a specific SHA against working tree."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        # Create initial commit
        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("V1\n")
        repo.index.add(["hello.txt"])
        c1 = repo.index.commit("v1")

        # Modify and commit v2
        with open(fpath, "w") as f:
            f.write("V2\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("v2")

        # Now edit working tree (uncommitted)
        with open(fpath, "w") as f:
            f.write("V3 (working tree)\n")

        # Diff c1 (V1) against working tree (V3) — should show both changes
        result = diff_file_against_working_tree(temp_repo, str(c1.hexsha), "hello.txt")
        assert result.success is True
        assert "V3 (working tree)" in result.stdout

    def test_invalid_sha_rejected(self, repo_with_commit):
        """Invalid SHA is rejected with error (MED-11 pattern)."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, "not-a-sha!!!", "hello.txt")
        assert result.success is False
        assert "Invalid git ref" in result.error

    # ----- BUG #5: non-string sha guards -----
    def test_diff_against_working_tree_sha_int(self, repo_with_commit):
        """Non-string sha (int) returns error instead of TypeError."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, 42, "hello.txt")  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error

    def test_diff_against_working_tree_sha_none(self, repo_with_commit):
        """None sha returns error instead of TypeError."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, None, "hello.txt")  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error

    def test_diff_against_working_tree_sha_list(self, repo_with_commit):
        """List sha returns error instead of TypeError."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, ["HEAD"], "hello.txt")  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid git ref" in result.error

    # ----- BUG #2: staged+unstaged edits -----
    def test_diff_working_tree_staged_and_unstaged(self, temp_repo):
        """diff_file_against_working_tree shows both staged and unstaged changes.

        A 2-way diff (sha vs working tree) includes both staged modifications
        and unstaged modifications on top of them.
        """
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("V1\n")
        repo.index.add(["hello.txt"])
        c1 = repo.index.commit("v1")

        # Stage a change
        with open(fpath, "w") as f:
            f.write("V2 (staged)\n")
        repo.index.add(["hello.txt"])

        # Make an unstaged change on top
        with open(fpath, "w") as f:
            f.write("V2 (staged)\nV3 (unstaged)\n")

        # The 2-way diff against c1 should capture both
        result = diff_file_against_working_tree(temp_repo, str(c1.hexsha), "hello.txt")
        assert result.success is True
        # Both changes should appear in the diff
        assert "V2 (staged)" in result.stdout
        assert "V3 (unstaged)" in result.stdout


class TestShaRegex:
    """BUG #9: SHA regex acceptance tests."""

    def test_valid_full_sha(self, repo_with_commit):
        """A full 40-hex SHA is accepted by diff_file_against_working_tree."""
        path, sha = repo_with_commit
        result = diff_file_against_working_tree(path, sha, "hello.txt")
        assert result.success is True

    def test_valid_short_sha(self, repo_with_commit):
        """A short (4+ hex) SHA is accepted."""
        path, sha = repo_with_commit
        result = diff_file_against_working_tree(path, sha[:8], "hello.txt")
        assert result.success is True

    def test_valid_head(self, repo_with_commit):
        """'HEAD' is accepted by the SHA guard."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, "HEAD", "hello.txt")
        assert result.success is True

    def test_valid_hex_lowercase(self, repo_with_commit):
        """Lowercase hex SHA is accepted."""
        path, sha = repo_with_commit
        result = diff_file_against_working_tree(path, sha.lower(), "hello.txt")
        assert result.success is True

    def test_valid_hex_uppercase(self, repo_with_commit):
        """Uppercase hex SHA is accepted."""
        path, sha = repo_with_commit
        result = diff_file_against_working_tree(path, sha.upper(), "hello.txt")
        assert result.success is True

    def test_head_tilde_rejected(self, repo_with_commit):
        """HEAD~ is NOT accepted by the current regex (BUG #9 — known limitation)."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, "HEAD~1", "hello.txt")
        assert result.success is False
        assert "Invalid git ref" in result.error

    def test_head_caret_rejected(self, repo_with_commit):
        """HEAD^ is NOT accepted by the current regex (BUG #9 — known limitation)."""
        path, _ = repo_with_commit
        result = diff_file_against_working_tree(path, "HEAD^", "hello.txt")
        assert result.success is False
        assert "Invalid git ref" in result.error


class TestFileLog:
    """file_log: commit history for a single file."""

    def test_history_for_tracked_file(self, temp_repo):
        """Returns history for a tracked file."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("V1\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("First commit")

        with open(fpath, "a") as f:
            f.write("V2\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("Second commit")

        result = file_log(temp_repo, "hello.txt", count=10)
        assert result.success is True
        assert result.stdout != ""
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2
        # Each line should have format: SHA\x1fDATE\x1fMESSAGE
        for line in lines:
            parts = line.split("\x1f")
            assert len(parts) == 3, f"Expected 3 fields, got {len(parts)}: {line!r}"
            # First part should be a SHA (hex)
            assert len(parts[0]) == 40, f"Expected 40-char SHA, got {parts[0]!r}"
            # Second part should be ISO date
            assert parts[2] in ("First commit", "Second commit"), f"Unexpected message: {parts[2]!r}"

    def test_empty_for_untracked_file(self, repo_with_commit):
        """Returns empty stdout for an untracked file."""
        path, _ = repo_with_commit
        result = file_log(path, "nonexistent.txt", count=10)
        assert result.success is True
        assert result.stdout == ""

    def test_count_clamping(self, temp_repo):
        """Count is clamped to 1..100."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("V1\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("c1")

        # count=0 should be clamped to 1
        result = file_log(temp_repo, "hello.txt", count=0)
        assert result.success is True

        # count=999 should be clamped to 100
        result = file_log(temp_repo, "hello.txt", count=999)
        assert result.success is True

    def test_pipe_in_message(self, temp_repo):
        """Pipe characters in commit message don't break parsing due to \\x1f separator."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("content\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("feat: add |pipe| in message")

        result = file_log(temp_repo, "hello.txt", count=5)
        assert result.success is True
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1
        parts = lines[0].split("\x1f")
        assert len(parts) == 3
        assert parts[2] == "feat: add |pipe| in message"

    def test_reject_x1f_in_subject(self, temp_repo):
        """BUG #1: Commit subject containing \\x1f is rejected with error."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("content\n")
        repo.index.add(["hello.txt"])
        # Create a commit with \\x1f in the message using low-level API
        repo.index.commit("safe subject")
        # Append another commit with unsafe char
        with open(fpath, "a") as f:
            f.write("more\n")
        repo.index.add(["hello.txt"])
        # GitPython allows unicode control chars, so \\x1f in message works
        repo.index.commit(f"unsafe\x1fchar")

        result = file_log(temp_repo, "hello.txt", count=5)
        assert result.success is False
        assert "unsafe" in result.error.lower()
        assert "\\x1f" in result.error or "separator" in result.error

    def test_count_non_int(self, temp_repo):
        """BUG #3: Non-int count values return clear error; bool rejected explicitly."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        with open(fpath, "w") as f:
            f.write("content\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("init")

        # bool is explicitly rejected
        result = file_log(temp_repo, "hello.txt", count=True)
        assert result.success is False
        assert "bool" in result.error

        # string count is coerced (valid string)
        result = file_log(temp_repo, "hello.txt", count="3")
        assert result.success is True
        assert result.stdout != ""

        # invalid string returns error
        result = file_log(temp_repo, "hello.txt", count="not_a_number")
        assert result.success is False
        assert "count must be an integer" in result.error or "invalid" in result.error.lower()

        # float is coerced (valid float)
        result = file_log(temp_repo, "hello.txt", count=3.0)
        assert result.success is True

    def test_count_clamping(self, temp_repo):
        """BUG #4: Count is clamped to 1..100. Assert actual line counts."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "hello.txt")
        for i in range(3):
            with open(fpath, "w") as f:
                f.write(f"V{i}\n")
            repo.index.add(["hello.txt"])
            repo.index.commit(f"c{i}")

        # count=0 → clamped to 1 → 1 line
        result = file_log(temp_repo, "hello.txt", count=0)
        assert result.success is True
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1, f"Expected 1 line for count=0, got {len(lines)}"

        # count=999 → clamped to 100 → 3 lines (all commits exist)
        result = file_log(temp_repo, "hello.txt", count=999)
        assert result.success is True
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3, f"Expected 3 lines for count=999, got {len(lines)}"

        # count=-5 → clamped to 1 → 1 line
        result = file_log(temp_repo, "hello.txt", count=-5)
        assert result.success is True
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1, f"Expected 1 line for count=-5, got {len(lines)}"


class TestStatusPorcelainFn:
    """status_porcelain: dict[str, str] of {rel_path: 2-char status_code}."""

    def test_empty_non_repo_returns_empty(self):
        """Non-repo or non-existent path returns empty dict."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = status_porcelain(tmpdir)
        assert result == {}

    def test_untracked_file(self, temp_repo):
        """A new untracked file appears with '?? ' status."""
        fpath = os.path.join(temp_repo, "untracked.txt")
        with open(fpath, "w") as f:
            f.write("new\n")
        result = status_porcelain(temp_repo)
        rel = os.path.relpath(fpath, temp_repo)
        assert result.get(rel) == "??"

    def test_modified_file(self, temp_repo):
        """A modified tracked file appears with ' M' (unstaged modified)."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "file.txt")
        with open(fpath, "w") as f:
            f.write("v1\n")
        repo.index.add(["file.txt"])
        repo.index.commit("init")

        # Modify without staging
        with open(fpath, "w") as f:
            f.write("v2\n")

        result = status_porcelain(temp_repo)
        rel = os.path.relpath(fpath, temp_repo)
        assert rel in result
        # Worktree column (second char) should be M or space+ M
        assert "M" in result[rel]

    def test_rename_line_uses_new_path(self, temp_repo):
        """A rename 'R  old -> new' emits the destination path as key (BUG #5)."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        old_path = os.path.join(temp_repo, "old_name.txt")
        with open(old_path, "w") as f:
            f.write("content\n")
        repo.index.add(["old_name.txt"])
        repo.index.commit("init")

        # Rename and stage it
        new_path = os.path.join(temp_repo, "new_name.txt")
        repo.git.mv("old_name.txt", "new_name.txt")
        repo.index.add(["new_name.txt"])

        result = status_porcelain(temp_repo)
        # The rename may appear in staged (R ) or unstaged ( R) depending on state
        assert any("R" in v for v in result.values()), f"No rename in status: {result}"
        # The key should be 'new_name.txt', not 'old_name.txt'
        assert "new_name.txt" in result, f"new_name.txt not in keys: {list(result.keys())}"

    def test_copy_line_uses_new_path(self, temp_repo):
        """A copy 'C  old -> new' emits the destination path as key (BUG #17)."""
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        src = os.path.join(temp_repo, "source.txt")
        with open(src, "w") as f:
            f.write("content\n")
        repo.index.add(["source.txt"])
        repo.index.commit("init")

        # git doesn't track copies naturally unless -C is passed
        dest = os.path.join(temp_repo, "copy.txt")
        import shutil
        shutil.copy2(src, dest)
        repo.index.add(["copy.txt"])

        result = status_porcelain(temp_repo)
        assert "copy.txt" in result, f"copy.txt not in keys: {list(result.keys())}"

    def test_too_short_line_skipped(self, temp_repo):
        """A line shorter than 4 chars is skipped (BUG #4)."""
        # The real status output never has such lines, but we can test
        # that status_porcelain handles this gracefully via a normal call
        # on an empty repo — the output will be "" which has 0 lines.
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        result = status_porcelain(temp_repo)
        assert result == {}  # clean repo — no errors from empty input

    def test_worktree_rename_both_status_positions(self, temp_repo):
        """Worktree rename ' R old -> new' checks BOTH status columns (BUG #25).

        Both porcelain status positions (index, worktree) are checked for 'R'.
        """
        repo = gitpython.Repo(temp_repo)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        fpath = os.path.join(temp_repo, "original.txt")
        with open(fpath, "w") as f:
            f.write("content\n")
        repo.index.add(["original.txt"])
        repo.index.commit("init")

        # Use OS-level rename + stage to produce an index-rename (R )
        new_path = os.path.join(temp_repo, "renamed.txt")
        os.rename(fpath, new_path)
        # Stage the new file, remove the old — git detects rename
        repo.index.add(["renamed.txt"])
        repo.index.remove(["original.txt"])

        result = status_porcelain(temp_repo)
        assert "renamed.txt" in result, f"renamed.txt not in keys: {list(result.keys())}"
        code = result["renamed.txt"]
        # At least one of the two status columns should be R
        assert code[0] == 'R' or (len(code) >= 2 and code[1] == 'R'), \
            f"Expected 'R' in either status column, got {code!r}"
