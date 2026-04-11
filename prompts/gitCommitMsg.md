# Git Commit Message Guide

Write commit messages that make code review fast and blame/`git log` useful. Bad messages = archaeology.

---

## Format

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

### Type

| Type | When to use |
|------|-------------|
| `feat` | New feature for the user |
| `fix` | Bug fix for the user |
| `docs` | Documentation only changes |
| `style` | Formatting, missing semicolons, etc. — no logic change |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `chore` | Maintenance tasks: deps, configs, build scripts |
| `ci` | CI/CD pipeline changes |
| `revert` | Reverting a previous commit |

### Scope

The affected module, package, or domain. Lowercase.

```
feat(auth): add OAuth2 PKCE flow
fix(payments): correct decimal rounding on refunds
refactor(gateway): extract nonce handling into separate class
```

### Subject

- Imperative mood: "add" not "added" or "adds"
- No period at the end
- Under 50 characters total for type+scope+subject
- Describe what changed, not what the code does

### Body (optional)

- Wrap at 72 characters
- Explain **why**, not what (the diff shows what)
- If there was a trade-off or alternative considered, note it

### Footer (optional)

```
Closes: #123
Fixes: #456
Related-To: #789
Reviewed-By: @teammate
```

---

## Decision Tree

**Before writing, ask:**

1. Is this a feat, fix, refactor, or chore?
2. What scope/package does this belong to?
3. In one line, what changed that the user or developer would care about?
4. If this commit appears in `git log --oneline` 6 months from now, will I know why?

---

## Anti-Patterns

| Bad | Why |
|-----|-----|
| `fixed stuff` | Useless |
| `asdfasdf` | What? |
| `Update file.py` | What changed? |
| `WIP` | Undefined scope |
| `fix bug` | Which bug? |
| `merged from feature/x` | Describes the mechanism, not the change |

---

## Good Examples

```
feat(auth): add device signature verification to WebSocket connect

Uses Ed25519 for device auth instead of sharing the gateway token.
The gateway requires v3 payload with device_id + nonce + signature.

Closes: #847
```

```
fix(gateway): prevent orphaned callbacks on reconnect

When stop() was called during an active connection, pending RPC callbacks
were never fired. Added _drain_pending() to flush all pending callbacks
with an error payload before closing the socket.

Fixes: #1203
```

```
chore(deps): upgrade websockets from 11.0 to 13.0

Required for Python 3.11 compatibility.
No API changes in this upgrade.
```

---

## Activation

Proceed with writing a commit message for: [describe the change, or say "review staged changes and write an appropriate message"]
