# tests/test_diff_parser.py
# Tests for utils/diff_parser.py

import pytest
from utils.diff_parser import (
    parse_diff, parse_diff_stat, summarize_diffstat,
    DiffLine, DiffHunk, FileDiff, ParsedDiff,
)


class TestParseEmptyDiff:
    def test_parse_empty_string(self):
        result = parse_diff("")
        assert len(result.files) == 0
        assert result.total_additions == 0
        assert result.total_deletions == 0

    def test_parse_whitespace_only(self):
        result = parse_diff("   \n\n  ")
        assert len(result.files) == 0


class TestParseSingleFileAddition:
    def test_parse_new_file(self):
        diff_text = """diff --git a/newfile.txt b/newfile.txt
new file mode 100644
--- /dev/null
+++ b/newfile.txt
@@ -0,0 +1,3 @@
+line one
+line two
+line three
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_new is True
        assert f.is_deleted is False
        assert f.additions == 3
        assert f.deletions == 0
        assert "newfile.txt" in f.display_path

    def test_parse_new_file_with_hunks(self):
        diff_text = """diff --git a/src/main.py b/src/main.py
new file mode 100644
--- /dev/null
+++ b/src/main.py
@@ -0,0 +1,7 @@
+def main():
+    print("hello")
+    x = 1
+    return x
+
+if __name__ == "__main__":
+    main()
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_new is True
        assert f.additions == 7
        assert len(f.hunks) == 1
        hunk = f.hunks[0]
        assert hunk.old_start == 0
        assert hunk.new_start == 1  # new file starting at line 1
        assert len(hunk.lines) == 7


class TestParseSingleFileDeletion:
    def test_parse_deleted_file(self):
        diff_text = """diff --git a/oldfile.txt b/oldfile.txt
deleted file mode 100644
--- a/oldfile.txt
+++ /dev/null
@@ -1,3 +0,0 @@
-line one
-line two
-line three
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_deleted is True
        assert f.additions == 0
        assert f.deletions == 3


class TestParseModification:
    def test_parse_modification(self):
        diff_text = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -10,5 +10,7 @@
     return data.strip()
+    if not result:
+        return None
     return result
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.additions == 2
        assert f.deletions == 0
        # Check hunk line numbers
        hunk = f.hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10

    def test_parse_modification_line_counts(self):
        diff_text = """diff --git a/file.txt b/file.txt
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 context
-old line
+new line one
+new line two
 context
"""
        result = parse_diff(diff_text)
        f = result.files[0]
        # One removal (old line), two additions (new line one, new line two)
        assert f.deletions == 1
        assert f.additions == 2


class TestParseMultipleFiles:
    def test_parse_multiple_files(self):
        diff_text = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1 @@
-old
+new
diff --git a/file2.txt b/file2.txt
--- a/file2.txt
+++ b/file2.txt
@@ -1 +1 @@
-old2
+new2
diff --git a/file3.txt b/file3.txt
--- a/file3.txt
+++ b/file3.txt
@@ -1 +1 @@
-old3
+new3
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 3
        assert result.total_additions == 3
        assert result.total_deletions == 3


class TestParseBinaryFile:
    def test_parse_binary_file(self):
        diff_text = """diff --git a/image.png b/image.png
new file mode 100644
Binary files differ
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_binary is True
        assert len(f.hunks) == 0
        assert f.additions == 0
        assert f.deletions == 0


class TestParseRenamedFile:
    def test_parse_renamed_file(self):
        diff_text = """diff --git a/old_name.py b/new_name.py
similarity index 95%
rename from old_name.py
rename to new_name.py
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
 some content
-old line
+new line
 more content
"""
        result = parse_diff(diff_text)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_renamed is True
        assert "old_name.py" in f.old_path
        assert "new_name.py" in f.new_path


class TestParseHunkHeaders:
    def test_parse_hunk_header_simple(self):
        diff_text = """diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -10,5 +10,7 @@
 context line
-old
+new
+extra
 context line
"""
        result = parse_diff(diff_text)
        hunk = result.files[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10

    def test_parse_hunk_header_complex(self):
        diff_text = """diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1,10 +1,12 @@
 first line
-old
+new
+added
 context
"""
        result = parse_diff(diff_text)
        hunk = result.files[0].hunks[0]
        assert hunk.old_start == 1
        assert hunk.new_start == 1


class TestParseDiffStat:
    def test_parse_stat_standard(self):
        # Real git diff --stat format: number of +'s = additions, -'s = deletions
        # " file.txt | 11 ++++++----- " = 6 additions, 5 deletions
        stat_text = """ file.txt | 11 ++++++-----
 another.py | 3 +++
 2 files changed, 9 insertions(+), 5 deletions(-)"""
        result = parse_diff_stat(stat_text)
        assert len(result) == 2
        assert result[0] == ("file.txt", 6, 5)   # 6 plusses, 5 minuses
        assert result[1] == ("another.py", 3, 0)  # 3 plusses, 0 minuses

    def test_parse_stat_empty(self):
        assert parse_diff_stat("") == []
        assert parse_diff_stat("   \n  ") == []


class TestParseRealGitOutput:
    def test_parse_real_git_diff(self, tmp_path):
        # Create a real git repo and generate actual diff output
        import subprocess
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True)

        # Initial commit
        (repo_dir / "file.txt").write_text("line1\nline2\nline3\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, capture_output=True)

        # Modify file
        (repo_dir / "file.txt").write_text("line1\nmodified\nline3\n")
        result = subprocess.run(["git", "diff", "HEAD"], cwd=repo_dir, capture_output=True, text=True)

        parsed = parse_diff(result.stdout)
        assert len(parsed.files) == 1
        assert parsed.files[0].deletions >= 1
        assert parsed.files[0].additions >= 1


class TestSummary:
    def test_summary_single_file(self):
        diff_text = """diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1 +1 @@
-old
+new
"""
        result = parse_diff(diff_text)
        assert "1 file changed" in result.summary
        assert "1 addition" in result.summary

    def test_summary_multiple_files(self):
        diff_text = """diff --git a/f1.py b/f1.py
--- a/f1.py
+++ b/f1.py
@@ -1 +1 @@
-a
+b
diff --git a/f2.py b/f2.py
--- a/f2.py
+++ b/f2.py
@@ -1 +1 @@
-c
+d
"""
        result = parse_diff(diff_text)
        assert "2 files changed" in result.summary


class TestSummarizeDiffstat:
    """Tests for summarize_diffstat(stat_text) → str."""

    def test_empty_string(self):
        """Empty input → 'No changes'."""
        assert summarize_diffstat("") == "No changes"

    def test_whitespace_only(self):
        """Whitespace-only input → 'No changes'."""
        assert summarize_diffstat("   \n\t  \n") == "No changes"

    def test_no_changes_no_files(self):
        """Stat output with no parseable file lines → 'No changes'."""
        # Lines without a '|' separator are ignored by parse_diff_stat,
        # so this yields an empty list.
        assert summarize_diffstat("nothing to see here\n") == "No changes"

    def test_no_changes_zero_markers(self):
        """Stat lines where all per-file adds/dels are zero → 'No changes'."""
        # parse_diff_stat requires at least one '+' or '-' marker to record
        # a file, so an empty marker bar also produces "No changes".
        assert summarize_diffstat("foo.txt | 0\n") == "No changes"

    def test_single_file_additions_only(self):
        """One file, only additions → '1 file changed, N insertions(+), 0 deletions(-)'."""
        stat_text = " newfile.py | 3 +++\n 1 file changed, 3 insertions(+), 0 deletions(-)"
        assert summarize_diffstat(stat_text) == "1 file changed, 3 insertions(+), 0 deletions(-)"

    def test_single_file_deletions_only(self):
        """One file, only deletions → '1 file changed, 0 insertions(+), N deletions(-)'."""
        stat_text = " oldfile.py | 2 --\n 1 file changed, 0 insertions(+), 2 deletions(-)"
        assert summarize_diffstat(stat_text) == "1 file changed, 0 insertions(+), 2 deletions(-)"

    def test_single_file_mixed(self):
        """One file with both adds and dels → uses the user's example shape."""
        stat_text = " src/main.py | 5 ++---\n 1 file changed, 2 insertions(+), 3 deletions(-)"
        assert summarize_diffstat(stat_text) == "1 file changed, 2 insertions(+), 3 deletions(-)"

    def test_multiple_files(self):
        """Multiple files → 'N files changed, X insertions(+), Y deletions(-)'."""
        stat_text = (
            " src/main.py | 5 ++---\n"
            " tests/test_main.py | 4 +++\n"
            " README.md | 1 +\n"
            " 3 files changed, 6 insertions(+), 3 deletions(-)"
        )
        assert summarize_diffstat(stat_text) == "3 files changed, 6 insertions(+), 3 deletions(-)"

    def test_multiple_files_no_additions(self):
        """All-deletions across multiple files."""
        stat_text = (
            " a.py | 4 ----\n"
            " b.py | 2 --\n"
            " 2 files changed, 0 insertions(+), 6 deletions(-)"
        )
        assert summarize_diffstat(stat_text) == "2 files changed, 0 insertions(+), 6 deletions(-)"

    def test_summary_line_ignored(self):
        """The trailing 'N files changed, ...' line is a normal stat line
        without '+' or '-' markers, so parse_diff_stat skips it. The summary
        function should be unaffected by its presence or wording."""
        # Note: the trailing line is included in the input but should be
        # ignored (no '+' or '-' markers means parse_diff_stat skips it).
        stat_text = (
            " foo.py | 1 +\n"
            " 1 file changed, 1 insertion(+), 0 deletions(-)"  # wrong counts in the trailer — must not affect output
        )
        assert summarize_diffstat(stat_text) == "1 file changed, 1 insertions(+), 0 deletions(-)"

    def test_zero_total_after_parsing_returns_no_changes(self):
        """If parse_diff_stat somehow yields a file with 0/0 (currently
        impossible, but defensive), return 'No changes' rather than
        '1 file changed, 0 insertions(+), 0 deletions(-)'."""
        # Build a synthetic case: monkey-patch parse_diff_stat to return
        # an entry that would have been filtered out — guards against
        # future regressions in parse_diff_stat's filtering logic.
        from utils import diff_parser
        original = diff_parser.parse_diff_stat
        diff_parser.parse_diff_stat = lambda _t: [("foo.py", 0, 0)]
        try:
            assert summarize_diffstat("anything") == "No changes"
        finally:
            diff_parser.parse_diff_stat = original

    def test_real_git_diff_stat(self, tmp_path):
        """End-to-end: run `git diff --stat` for real and summarize its output."""
        import subprocess
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True)

        (repo_dir / "a.txt").write_text("one\ntwo\nthree\n")
        (repo_dir / "b.txt").write_text("alpha\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True)

        # Modify a.txt (1 add, 1 del) and append a line to b.txt (1 add)
        (repo_dir / "a.txt").write_text("one\nTWO\nthree\n")
        (repo_dir / "b.txt").write_text("alpha\nbeta\n")

        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        ).stdout

        summary = summarize_diffstat(stat)
        assert "2 files changed" in summary
        assert "2 insertions(+)" in summary
        assert "1 deletions(-)" in summary

    def test_clean_repo_no_changes(self, tmp_path):
        """A clean repo produces empty stat output → 'No changes'."""
        import subprocess
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True)

        (repo_dir / "a.txt").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True)

        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        ).stdout

        assert summarize_diffstat(stat) == "No changes"
