# Codebase Research

Understand an unfamiliar codebase quickly and accurately. Don't assume — read the code. Don't guess the architecture — derive it from evidence.

---

## Phase 1: Orientation (5 minutes)

Before reading any code:

1. Find and read the README
2. Find the entry point (`main`, `index`, `app`, `__main__`)
3. Find the dependency manifest (`package.json`, `requirements.txt`, `go.mod`, `Cargo.toml`)
4. Identify the language, framework, and key libraries
5. Look at the directory structure — what are the top-level folders?

---

## Phase 2: Trace the Execution Path

1. Start at the entry point
2. Trace what gets imported and in what order
3. Find the main event loop or request handler
4. Identify where external input enters the system (HTTP, WebSocket, CLI, file, message queue)
5. Map each input to the code that handles it

---

## Phase 3: Data Flow

For each major flow:

1. Where does data enter this flow?
2. What transformations does it go through?
3. Where does it get persisted or transmitted?
4. Where does it exit the system?

---

## Phase 4: Key Components

For each major component you identify:

| Question | Why it matters |
|----------|---------------|
| What does it own? | Encapsulation, responsibility |
| What depends on it? | Change impact |
| What does it depend on? | Failure propagation |
| Where is it instantiated? | Lifecycle |
| Is it a singleton or transient? | Thread safety |

---

## Evidence Checklist

Document with actual evidence from the code:

- [ ] Entry point identified with file path and line
- [ ] Directory structure mapped (show the tree)
- [ ] External dependencies listed with version
- [ ] All major flows traced with function names and line numbers
- [ ] Configuration sources identified (env vars, config files, secrets)
- [ ] Error handling patterns identified (try/catch? result types? panic?)
- [ ] Test strategy identified (what's tested, what isn't)

---

## Output Format

```
## Overview
[Language, framework, total lines of code estimate]
[What the system does in one sentence]

## Architecture

### Directory Structure
```
[ tree ]
```

### Entry Point
`[file]:[line]` — `[what it does]`

### External Dependencies
| Library | Version | Purpose |
|---------|---------|---------|
| ... | | |

### Data Flows

#### Flow: [Name]
**Entry:** `[where data enters]`
**Path:** `[entry]` → `[transform]` → `[persist/transmit]` → `[exit]`
**Key files:** `[list with lines]`

## Key Components

### [Component Name]
- **File:** `[path]`
- **Responsibility:** `[one sentence]`
- **Depends on:** `[list]`
- **Used by:** `[list]`
- **Lifecycle:** singleton / transient / per-request

## Configuration
[Where config comes from — env vars, files, etc.]

## Testing
[What's tested, what's not, test file locations]

## Open Questions
[Things that are unclear and need further investigation]
```

---

## Common Pitfalls

| Pitfall | Why it's bad | Fix |
|---------|--------------|-----|
| Reading code before understanding structure | Get lost in details | Always do Phase 1 first |
| Assuming naming = behavior | Names lie | Read the actual code |
| Not checking tests | Tests reveal behavior | Find and read relevant tests |
| Missing the error handling | Error paths define reliability | Trace the catch/except blocks |
| Not checking config | Hardcoded secrets or magic values | Find where config is loaded |

---

## Activation

Proceed with researching the codebase at: [path to codebase]
