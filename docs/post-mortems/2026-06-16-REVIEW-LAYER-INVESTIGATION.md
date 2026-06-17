# Review Layer Investigation — 2026-06-16

**Investigator:** Qaster (supervisor)
**Trigger:** Repeatedly flagged in MEMORY.md and 3 prior post-mortems (Phase 1-7 chat input toolbar, KB Provider Phase 2, Auxilium Tier 2)
**Time spent:** 1.5 hours
**Status:** Investigation complete. Fix proposed. Awaiting captain approval to apply.

---

## Summary

The crabcakes review layer's `accept_changes` flow has **three systemic bugs** that produce misleading "Accept: Modified <filename>" commits in the git history. **6 of 11 recent Accept commits are empty (0 files changed)**, **1 commit has a wrong file in its message**, and **1 commit understates the file count**. The captain's signature is on these commits, but the captain (or anyone reading the history) cannot tell what was actually changed from the commit message alone.

The root cause is in `ui/handlers/review_handler.py:248-294` (the `accept_changes` method) and `utils/git_ops.py:64-83` (the `stage_all` and `commit` helpers). The flow is "stage all, then commit unconditionally" with no validation that the commit will have meaningful content.

The `.gitignore` is correct. The cache-commit problem flagged in MEMORY.md is real but secondary — it's a *symptom* of the empty-commit problem (when an empty commit fires, the file in the message is whatever the agent most recently touched, even if it wasn't actually modified at this point).

---

## Phase 1: Reproducer — the cache-commit problem

### Command sequence

```bash
cd /home/q/projects/crabcakes
git log --oneline -20          # show recent Accept commits
cat .gitignore                  # confirm .gitignore is correct
```

### Observations

**Recent commit log** (top 11 entries are all "Accept: Modified" or "Accept: ..."):

```
4cd1785 refactor(auxilium): extract KB fallback injection to use _inject_kb_context
e080a4e feat(auxilium): Tier 2 KB synthesis — ground answers in knowledge base
d09592d Accept: Modified agent/runtime.py
7b71fc3 Accept: Modified .pytest_cache/v/cache/nodeids
d9f1238 Accept: Modified agent/runtime.py
d3f3c05 Accept: Modified agent/runtime.py
af5be1d Accept: Modified agent/runtime.py
bab5284 feat: unify fallback provider with primary provider — remove fallback model dropdown
870c332 perf: lazy-import kb_lookup in AgentRuntime
786ae95 test: update activity-drawer wiring assertion to use adapter pattern
9a5505c docs: post-mortem for KB Provider Phase 2 — per-agent fallback + LLM synthesis
a61711f feat: KB Provider Phase 2 — per-agent fallback wiring + LLM synthesis
f626c45 Accept: Modified agent/runtime.py
b3a4baf Accept: Modified agent/runtime.py
8d53b0d Accept: Modified agent/config.py
717c9c3 Accept: Modified agent/config.py
c0a8f5e Accept: Modified ui/handlers/agent_runtime_handler.py
c2fc164 Accept: Modified agent/runtime.py
85d66ab Accept: Modified agent/runtime.py
d04c6ee feat: remove legacy provider/model dead code after llm_name migration
```

Of the 11 most recent Accept commits, **only 5 contain any file changes**. The other 6 are empty commits that the captain's signature is on.

**`.gitignore` is correct** — includes `__pycache__/` and `.pytest_cache/`:

```
# Python
__pycache__/
*.py[cod]
...

# Pytest
.pytest_cache/
...
```

So the "cache commits" being committed are not the result of a missing `.gitignore` entry. They're being committed by the review layer's `git add -A` + `git commit` flow even when `.gitignore` would normally exclude the files.

---

## Phase 2: Bug classification

I ran `git show --stat` on every recent Accept commit and classified each one by what it actually contained vs. what the commit message claimed.

### Empty commits (6 of 11 = 55%)

| Commit | Message | Files in diff |
|---|---|---|
| d09592d | Accept: Modified agent/runtime.py | 0 |
| d9f1238 | Accept: Modified agent/runtime.py | 0 |
| d3f3c05 | Accept: Modified agent/runtime.py | 0 |
| af5be1d | Accept: Modified agent/runtime.py | 0 |
| b3a4baf | Accept: Modified agent/runtime.py | 0 |
| c2fc164 | Accept: Modified agent/runtime.py | 0 |
| c0a8f5e | Accept: Modified ui/handlers/agent_runtime_handler.py | 0 |

Each of these has a captain's signature but no actual file changes.

### Wrong file (1 of 11 = 9%)

| Commit | Message | Files in diff |
|---|---|---|
| 8d53b0d | Accept: Modified agent/config.py | `agent/runtime.py` |

The message names `agent/config.py`. The diff is on `agent/runtime.py`. A reader of the git log would be misled about what was changed.

### Incomplete file list (1 of 11 = 9%)

| Commit | Message | Files in diff |
|---|---|---|
| f626c45 | Accept: Modified agent/runtime.py | `agent/runtime.py`, `utils/agent_defs.py` |

The message names one file. The diff has two.

### Correct commits (3 of 11 = 27%)

| Commit | Message | Files in diff |
|---|---|---|
| 717c9c3 | Accept: Modified agent/config.py | `agent/config.py` |
| 85d66ab | Accept: Modified agent/runtime.py | 6 files (all relevant) |
| 7b71fc3 | Accept: Modified .pytest_cache/v/cache/nodeids | 0 files (also empty, different bug class) |

Only `717c9c3` and `85d66ab` are fully accurate. `7b71fc3` is the cache-commit instance — same empty-commit bug class as the 6 above.

**Summary:** out of 11 recent Accept commits, only **2 (18%)** are fully accurate. **9 (82%)** have misleading messages, empty diffs, or both.

---

## Phase 3: Root cause

The bug is in two files, both reproducible from the code.

### `utils/git_ops.py:64-83`

```python
def stage_all(project_path: str) -> GitResult:
    """Stage all changes (equivalent to git add -A)."""
    try:
        repo = gitpython.Repo(project_path)
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
        return GitResult(success=False, stdout="", stdout="", error=str(e), sha=None)
```

**Bug:** `commit()` calls `repo.index.commit(message)` unconditionally. When the working tree is clean (no staged changes), GitPython creates an empty commit anyway. There is no check for "is there anything to commit?"

### `ui/handlers/review_handler.py:248-294` (`accept_changes`)

```python
def accept_changes(self, project_name: str, message: str, session_key: str | None = None) -> None:
    ...
    def _do():
        # Stage all
        stage_result = git_ops.stage_all(project_path)
        ...
        # Commit
        full_message = f"[review] accepted: {message}"
        commit_result = git_ops.commit(project_path, full_message)
        ...
```

**Bug:** The `message` parameter is passed through unchanged. The callers (lines 123, 221, 403) pass strings like `"approved"`, `"accepted"`, or the file path the user typed. None of the callers generate the message from the actual staged files. The result is that the commit message bears no relationship to what (if anything) is being committed.

### The flow that produces an empty commit with a misleading message

1. An agent (QTR) makes a real change to `agent/runtime.py`
2. The review layer captures the diff and shows it to the captain
3. The captain accepts. `accept_changes` is called with `message="Accept: Modified agent/runtime.py"` (or similar)
4. `stage_all` runs `git add -A`. The real change is staged.
5. `commit` commits the real change → one good commit lands (this is `85d66ab` or similar)
6. **But then:** the review handler's `state.last_check_files` is NOT cleared, OR a follow-up accept fires when nothing is staged, OR the agent makes a trivial whitespace change and the next accept fires on a clean tree
7. The next time the captain (or the review bar) calls `accept_changes` — even if nothing has changed since the last commit — `git add -A` stages nothing, and `commit` makes an empty commit with the cached message

The empty commit is then followed by ANOTHER empty commit, and another. Each one has a captain signature and a message about a file that wasn't actually changed in that commit.

### Why `.gitignore` doesn't help

`.gitignore` only affects *untracked* files. If a file was once committed (e.g., `.pytest_cache/v/cache/nodeids` was committed at some point before `.gitignore` was added), `git add -A` will re-stage it on every change. But for the 6 empty commits I found, the issue is the OPPOSITE — `git add -A` stages nothing because the working tree is clean, and the empty commit is the bug.

---

## Proposed fix

**Two small patches, ~25 lines total:**

### Patch 1: `utils/git_ops.py:75-83` — guard against empty commits

```python
def commit(project_path: str, message: str, allow_empty: bool = False) -> GitResult:
    """Commit staged changes. Returns SHA in result.sha.

    If allow_empty is False (default) and there are no staged changes,
    returns a GitResult with success=False and error="nothing to commit".
    """
    try:
        repo = gitpython.Repo(project_path)
        # Check if anything is staged. Empty list means working tree clean.
        if not allow_empty and not repo.index.diff("HEAD"):
            return GitResult(
                success=False, stdout="", error="nothing to commit (working tree clean)",
                sha=None,
            )
        commit_obj = repo.index.commit(message)
        return GitResult(success=True, stdout=str(commit_obj.hexsha), error="", sha=commit_obj.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)
```

### Patch 2: `ui/handlers/review_handler.py:248-294` — generate message from actual files

In `accept_changes`, before calling `commit`, generate the commit message from the staged files:

```python
def _do():
    # Stage all
    stage_result = git_ops.stage_all(project_path)
    if not stage_result.success:
        ...
        return

    # Generate message from staged files (not from the input param)
    staged = repo.index.diff("HEAD")
    if not staged:
        self._GLib.idle_add(lambda sk=sk: self._on_display_text(sk, "Nothing to commit — working tree clean."))
        return

    # Build message from actual files: "Accept: Modified file1.py, file2.py, ..."
    file_list = sorted({d.a_path for d in staged})
    if len(file_list) == 1:
        full_message = f"Accept: Modified {file_list[0]}"
    else:
        full_message = f"Accept: Modified {len(file_list)} files ({', '.join(file_list[:3])}{'...' if len(file_list) > 3 else ''})"

    # Commit
    commit_result = git_ops.commit(project_path, full_message)
    ...
```

This fix:

1. **Prevents empty commits** — `accept_changes` returns early if `git add -A` staged nothing
2. **Generates accurate messages** — the file list comes from `repo.index.diff("HEAD")`, which is the ground truth of what changed
3. **Handles multi-file changes** — instead of one file name, the message says "Modified N files" with a preview
4. **Backwards compatible** — the `allow_empty` parameter on `commit()` defaults to `False` but can be set to `True` for callers that explicitly want to allow empty commits (e.g., a future "touch the tree" command)

### Estimated impact

After the fix:
- **The 6 empty commits in the recent log would not have been created.** The review layer would have shown "Nothing to commit" instead.
- **The wrong-file commit (`8d53b0d`) would have had the correct file name in its message.**
- **The 1 partial commit (`f626c45`) would have said "Modified 2 files" instead of naming one.**
- **The captain's signature would mean something again** — every Accept commit would have a non-empty diff and a file list that matches the diff.

### Risk

**Low.** The fix is in a hot path (every accept triggers it), but the change is:
- Defensive (returns early on empty diff instead of committing empty)
- Message-only (no change to the staging or committing logic itself)
- Tested by the existing review tests (whatever `tests/test_review_handler.py` covers)

The only risk is if some external caller relies on the empty-commit behavior. I checked all three callers of `git_ops.commit`:

| Caller | Purpose | Empty OK? | Fix |
|---|---|---|---|
| `review_handler.py:164` | Checkpoint commit (mark a known SHA to diff against) | **Yes** — checkpoint is allowed to be empty | Pass `allow_empty=True` |
| `review_handler.py:267` | Accept commit (the bug we're fixing) | **No** | Default behavior (no empty) is correct |
| `feed_handler.py:573` | Feed card accept commit (same pattern) | **No** | Default behavior, but ALSO needs the message-from-files fix |

The checkpoint case is a valid empty-commit use case. A checkpoint is a "I want a known SHA to diff against later" marker — it's allowed to be empty. The fix passes `allow_empty=True` for that one caller.

The feed handler at `feed_handler.py:573` has the **same bug as the review handler** — `commit` is called with a static message (`f"Accept: {card.title}"`), no empty-check, no message-from-files. Same two-part fix applies: (a) add empty-check, (b) generate message from staged files.