# utils/diff_parser.py
# Parses unified diff output into structured data.
# Pure function — no GTK, no git calls, no file I/O.

import re
from dataclasses import dataclass


@dataclass
class DiffLine:
    """A single line in a diff hunk."""
    type: str              # "add" | "remove" | "context" | "header"
    content: str           # the actual line content (without +/- prefix)
    old_line_no: int | None
    new_line_no: int | None


@dataclass
class DiffHunk:
    """A contiguous block of changes in a file."""
    header: str            # e.g. "@@ -10,5 +10,7 @@"
    old_start: int
    new_start: int
    lines: list[DiffLine]


@dataclass
class FileDiff:
    """All changes to a single file."""
    old_path: str          # e.g. "a/src/main.py"
    new_path: str          # e.g. "b/src/main.py"
    display_path: str      # e.g. "src/main.py" (cleaned)
    is_binary: bool
    is_new: bool           # newly created file
    is_deleted: bool       # deleted file
    is_renamed: bool      # renamed file
    hunks: list[DiffHunk]
    additions: int         # count of added lines
    deletions: int         # count of removed lines


@dataclass
class ParsedDiff:
    """Complete parsed diff output."""
    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    summary: str           # e.g. "3 files changed, 42 additions(+), 7 deletions(-)"


def parse_diff(diff_text: str) -> ParsedDiff:
    """
    Parse unified diff output into structured data.

    Args:
        diff_text: Raw output from `git diff` or `git diff <sha>`

    Returns:
        ParsedDiff with per-file, per-hunk, per-line breakdown.

    Handles:
        - New files (--- /dev/null)
        - Deleted files (+++ /dev/null)
        - Renamed files (diff --git a/old b/new)
        - Binary files (Binary files differ)
        - Empty diffs (no changes)
    """
    if not diff_text or not diff_text.strip():
        return ParsedDiff(files=[], total_additions=0, total_deletions=0, summary="No changes")

    files: list[FileDiff] = []
    total_additions = 0
    total_deletions = 0

    # Split into file-level blocks
    # Pattern: diff --git a/old b/new\n ... [hunks] ...
    file_blocks = _split_into_file_blocks(diff_text)

    for block in file_blocks:
        file_diff, adds, dels = _parse_file_block(block)
        if file_diff:
            files.append(file_diff)
            total_additions += adds
            total_deletions += dels

    file_count = len(files)
    if file_count == 0:
        summary = "No changes"
    elif file_count == 1:
        f = files[0]
        summary = f"1 file changed, {total_additions} additions(+), {total_deletions} deletions(-)"
    else:
        summary = f"{file_count} files changed, {total_additions} additions(+), {total_deletions} deletions(-)"

    return ParsedDiff(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
        summary=summary,
    )


def _split_into_file_blocks(diff_text: str) -> list[str]:
    """Split diff text into per-file blocks."""
    # Match lines that start a new file diff
    lines = diff_text.splitlines(keepends=False)
    blocks = []
    current = []

    for line in lines:
        if line.startswith("diff --git"):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks


def _parse_file_block(block: str) -> tuple[FileDiff | None, int, int]:
    """Parse a single file diff block. Returns (FileDiff, additions, deletions)."""
    lines = block.splitlines()
    if not lines:
        return None, 0, 0

    is_binary = False
    is_new = False
    is_deleted = False
    is_renamed = False
    old_path = ""
    new_path = ""
    display_path = ""

    hunks: list[DiffHunk] = []
    additions = 0
    deletions = 0

    # Parse header lines
    for line in lines:
        if line.startswith("diff --git"):
            # Extract paths from "diff --git a/old b/new"
            # Handle "diff --git a/old b/new" (renamed) or "diff --git a/file b/file"
            parts = line.split(" ", 3)
            if len(parts) >= 4:
                old_path = parts[2].removeprefix("a/")
                new_path = parts[3].removeprefix("b/")
                is_renamed = old_path != new_path
                display_path = new_path if new_path else old_path
        elif line.startswith("--- "):
            if "/dev/null" in line:
                is_new = True
            else:
                # Extract path after "--- "
                path_part = line[4:].strip()
                if path_part.startswith("a/"):
                    path_part = path_part[2:]
                old_path = path_part
        elif line.startswith("+++ "):
            if "/dev/null" in line:
                is_deleted = True
            else:
                # Extract path after "+++ "
                path_part = line[4:].strip()
                if path_part.startswith("b/"):
                    path_part = path_part[2:]
                new_path = path_part
                if not display_path:
                    display_path = path_part
        elif "Binary files differ" in line:
            is_binary = True

    # If old_path and new_path are empty, try to infer from the block content
    if not old_path and not new_path:
        return None, 0, 0

    if is_binary:
        # Binary files have no hunks
        file_diff = FileDiff(
            old_path=old_path,
            new_path=new_path,
            display_path=display_path,
            is_binary=True,
            is_new=is_new,
            is_deleted=is_deleted,
            is_renamed=is_renamed,
            hunks=[],
            additions=0,
            deletions=0,
        )
        return file_diff, 0, 0

    # Parse hunks
    current_hunk_lines: list[DiffLine] = []
    hunk_header = ""
    hunk_old_start = 0   # starting line for old file (from @@ header)
    hunk_new_start = 0   # starting line for new file (from @@ header)
    old_line = 0         # running line number for old file
    new_line = 0         # running line number for new file

    for line in lines:
        if line.startswith("@@"):
            # Save previous hunk if any
            if current_hunk_lines:
                hunks.append(DiffHunk(
                    header=hunk_header,
                    old_start=hunk_old_start,
                    new_start=hunk_new_start,
                    lines=current_hunk_lines,
                ))
                current_hunk_lines = []

            # Parse @@ -old_start,old_count +new_start,new_count @@
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
            if m:
                hunk_old_start = int(m.group(1))
                hunk_new_start = int(m.group(2))
                hunk_header = line
            else:
                hunk_header = line
                hunk_old_start = 0
                hunk_new_start = 0
            # Reset running counters to the starting line numbers
            old_line = hunk_old_start
            new_line = hunk_new_start
        elif line.startswith("+") and not line.startswith("+++"):
            # Added line
            content = line[1:]
            current_hunk_lines.append(DiffLine(
                type="add",
                content=content,
                old_line_no=None,
                new_line_no=new_line,
            ))
            new_line += 1
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            # Removed line
            content = line[1:]
            current_hunk_lines.append(DiffLine(
                type="remove",
                content=content,
                old_line_no=old_line,
                new_line_no=None,
            ))
            old_line += 1
            deletions += 1
        elif line.startswith(" ") or line == "":
            # Context line
            content = line[1:] if line else ""
            current_hunk_lines.append(DiffLine(
                type="context",
                content=content,
                old_line_no=old_line,
                new_line_no=new_line,
            ))
            old_line += 1
            new_line += 1

    # Save last hunk
    if current_hunk_lines:
        hunks.append(DiffHunk(
            header=hunk_header,
            old_start=hunk_old_start,
            new_start=hunk_new_start,
            lines=current_hunk_lines,
        ))

    file_diff = FileDiff(
        old_path=old_path,
        new_path=new_path,
        display_path=display_path,
        is_binary=is_binary,
        is_new=is_new,
        is_deleted=is_deleted,
        is_renamed=is_renamed,
        hunks=hunks,
        additions=additions,
        deletions=deletions,
    )

    return file_diff, additions, deletions


def parse_diff_stat(stat_text: str) -> list[tuple[str, int, int]]:
    """
    Parse `git diff --stat` output.

    Returns:
        [(file_path, additions, deletions), ...]
    """
    result = []
    if not stat_text:
        return result

    for line in stat_text.strip().splitlines():
        # Format: "file/path.py | 12 +++---" where:
        #   - the leading number is total changes
        #   - + marks indicate additions, - marks indicate deletions
        # e.g. " 5 ++---" = 2 additions (++), 3 deletions (---)
        # e.g. "10 ++++++" = 10 additions, 0 deletions
        parts = line.split("|")
        if len(parts) != 2:
            continue

        file_path = parts[0].strip()
        stats_part = parts[1].strip()

        # Count + and - markers directly
        additions = stats_part.count("+")
        deletions = stats_part.count("-")

        if additions == 0 and deletions == 0:
            continue

        result.append((file_path, additions, deletions))

    return result
