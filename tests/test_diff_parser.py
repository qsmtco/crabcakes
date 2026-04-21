# tests/test_diff_parser.py
# Tests for utils/diff_parser.py

import pytest
from utils.diff_parser import (
    parse_diff, parse_diff_stat,
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
