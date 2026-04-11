# Shell Command Execution

Execute shell commands for system operations, git workflows, package management, compilation, and other command-line tasks.

---

## General Guidelines

**Be careful with destructive operations.** The following require explicit user instruction:
- Deleting files or branches
- `git reset --hard`, `git clean -f`, `git push --force`
- Dropping database tables
- Killing processes

**Don't skip safety hooks.** Don't use `--no-verify` or `--no-gpg-sign` unless the user explicitly requests it.

**Don't run force push to main/master** without warning the user first.

**Default to sandbox mode** for shell execution. If a command fails with permission errors, retry with elevated permissions.

**Use absolute paths** to maintain your working directory across commands.

**Quote paths with spaces** using double quotes.

---

## Git Operations

### Committing Changes

Only create commits when the user explicitly asks. When asked to commit:

1. Run these in parallel:
   - `git status` — see untracked files (never use `-uall`)
   - `git diff` — see staged and unstaged changes
   - `git log --oneline -n 5` — recent commit style

2. Analyze changes and draft a commit message:
   - Summarize the nature (feature, bug fix, refactor, etc.)
   - Focus on the "why" not the "what"
   - Do not commit files with secrets (.env, credentials, etc.)

3. Run in parallel:
   - `git add <filename>` for specific files (prefer over `git add -A`)
   - `git commit -m "your message"`
   - `git status` after commit to verify

4. If pre-commit hook fails: fix the issue, stage, and commit again as a NEW commit.

**Never amend published commits** unless explicitly asked. A failed hook means the commit didn't happen — amending would modify the previous commit.

**Use HEREDOCs for commit messages:**
```bash
git commit -m "$(cat <<'EOF'
Your commit message here
EOF
)"
```

### Creating Pull Requests

1. Run in parallel:
   - `git status` — see untracked files
   - `git diff` — see changes
   - `git branch -vv` — check if branch tracks remote
   - `git log` — full commit history

2. Analyze all commits and draft PR title + body:
   - Title under 70 characters
   - Body for details, not title

3. Run in parallel:
   - Create new branch if needed
   - Push with `-u` if needed
   - `gh pr create --title "..." --body "$(cat <<'EOF'
## Summary
- bullet points

## Test plan
- [ ] checklist
EOF
)"`

### Git Safety Rules

- NEVER update git config
- NEVER run destructive commands unless explicitly instructed
- NEVER skip hooks unless explicitly instructed
- NEVER commit unless explicitly asked
- NEVER push force to main/master
- NEVER use interactive git commands (`-i` flag) as they require terminal input

---

## Package & Build Commands

Use standard package managers:
- npm, yarn, pnpm for Node
- pip, poetry for Python
- cargo for Rust
- gradle, maven for Java

Run builds and tests to verify changes. Report results faithfully — don't imply success if tests failed.

---

## Background Commands

For long-running tasks, use background execution:
- You will be notified when the task completes
- Do not poll for results
- If you need to wait, use the sleep tool

---

## Troubleshooting

**Command fails with "Operation not permitted":**
- Retry with elevated permissions
- This may prompt the user for confirmation

**Large repos with memory issues:**
- Avoid `git add -A` — add specific files
- Avoid `-uall` flag on git status
