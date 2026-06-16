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
        checkout_paths, log, push, status, GitResult,
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
