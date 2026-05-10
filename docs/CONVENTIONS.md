# Project Conventions

> **Status: ACTIVE REFERENCE** — Conventions still followed in codebase as of 2026-05-09.

**Date:** 2026-04-27
**Author:** Qaster
**Status:** Active

---

## context.md — Human-Readable by Convention

`.crabcakes/context.md` is a **human-readable markdown file**. It serves as a shared notepad between agents and the PM.

### Why Human-Readable
- The PM can open and read it at any time
- It doubles as a lightweight changelog
- Machine-only formats (JSON, YAML) are fragile — one bad parse and agents lose context
- Markdown is universal and resilient

### Format
```markdown
# {project_name} — Project Context

## YYYY-MM-DD — {topic}
- Bullet points, concise
- Dated entries, newest last
- No secrets, no verbose logs
```

### Rules
- Agents append dated entries, they don't restructure existing ones
- Keep entries concise — this is a notepad, not a log file
- If the PM reads it, it should make sense immediately

---

## Phase Gates

All CrabCakes workflow phases follow a strict **gate system**:

1. **No phase crossing without PM approval.** The agent completes a phase, summarizes what was done, and asks for explicit go-ahead.
2. **Narration required.** At each step, the agent briefly explains what it's doing and why.
3. **No building during onboarding or discovery.** Application code is only written in the implementation phase.

### Phase Sequence
Onboarding → (gate) → Discovery → (gate) → Architecture → (gate) → Task Planning → (gate) → Implementation → Testing → Ship

---

## Onboarding Standards

### Code Style & Tooling
Onboarding defaults to **industry-standard** tooling. Don't ask the PM "what linter do you prefer?" — present the standards and ask for confirmation:

| Language | Linter | Formatter | Type Check | Test Runner |
|----------|--------|-----------|------------|-------------|
| Python | Ruff | Black + Ruff | mypy | pytest |
| JavaScript/TS | ESLint | Prettier | TypeScript strict | Vitest |
| Rust | clippy | rustfmt | built-in | cargo test |
| Go | go vet | gofmt | built-in | go test |

### Opening Message
The agent's first message must:
1. Use the **project name**
2. Say **"Let's begin the onboarding process"**
3. Ask what we're building (freeform)

### Order of Questions
1. Purpose (what are we building?)
2. Stack & dependencies
3. Entry points
4. Code style & tooling (propose industry defaults)
5. Team members & roles
