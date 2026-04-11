# Prompt Library — Index

Every agent: read this file first. Find the right prompt for your task in seconds.

---

## How to Use This Library

1. Find the section matching your task type
2. Read the file name and summary
3. Load the file with `read` and follow its instructions
4. Use `workflow.md` if none of these match — it's the fallback

---

## Writing Code

*Create, modify, or generate code with verified steps and minimal waste.*

| File | What it does | Key words |
|------|-------------|-----------|
| `codeWriter.md` | Tiny verified steps, ≤15 lines per checkpoint, constant validation | write code, new feature, refactor, verified steps, atomic |
| `codeRefactor.md` | Improve messy code without changing behavior | clean code, restructure, technical debt, improve |
| `fullStackGenerator.md` | Build complete full-stack apps from scratch | full-stack, frontend, backend, scaffold |
| `sqlWriter.md` | Queries, schemas, migrations — correct and performant | SQL, PostgreSQL, queries, migrations, schema, indexes |
| `dockerWriter.md` | Dockerfiles, docker-compose, multi-stage builds | Docker, containers, docker-compose, images, build |
| `dataModeling.md` | Schema design, ER diagrams, indexing strategy | database schema, ERD, relationships, entities, modeling |

---

## Testing

*Write tests that find bugs, not just confirm the happy path.*

| File | What it does | Key words |
|------|-------------|-----------|
| `codeTester.md` | Tests that prove code breaks, not passes | edge cases, failure, adversarial, prove wrong |
| `testDataGenerator.md` | Generate realistic fixtures and test data | fixtures, test data, factory, seeds |
| `loadTesting.md` | Stress test, soak test, spike test, find breaking point | k6, Locust, stress test, performance, throughput, latency |

---

## Debugging

*Find root causes fast. One hypothesis at a time. No guessing.*

| File | What it does | Key words |
|------|-------------|-----------|
| `codeDebugger.md` | One hypothesis at a time, minimal repro, rank by probability | debugging, hypothesis, reproduce, root cause |
| `adversarialDebugger.md` | Attack every assumption, find what breaks under pressure | adversarial, assumptions, failure modes, destroy |
| `incidentDebugger.md` | Debug a live incident, triage, communicate status | incident, outage, production, on-call, triage |
| `bugFinder.md` | Systematic probe for hidden defects | defect, hidden bug, edge case, probe |

---

## Code Quality

*Audit, review, and harden existing codebases.*

| File | What it does | Key words |
|------|-------------|-----------|
| `codeAudit1.md` | Full quality audit — wiring, logic, security, tests | audit, review, quality, quality gate |
| `codeAudit2.md` | Alternative audit checklist (ManoPea-specific) | audit, review, checklist |
| `codeAuditGeneral.md` | General-purpose adversarial audit for any project | audit, review, quality gate, adversarial |
| `dependencyAudit.md` | Check for outdated deps, vulnerabilities, circular imports | dependencies, packages, imports, versions |
| `errorHandlingReview.md` | Audit error handling patterns | errors, exceptions, try/catch, error handling |
| `performanceOptimizer.md` | Profile and fix slow code | performance, bottleneck, profiling, optimize |
| `securityAudit.md` | OWASP, injection, auth, secrets, XSS, CSRF | security, OWASP, injection, auth, secrets, XSS, SQL injection |
| `accessibilityAudit.md` | Keyboard nav, screen readers, contrast, WCAG 2.1 AA | a11y, accessibility, WCAG, keyboard nav, screen reader, contrast |

---

## Architecture & Structure

*Design and verify how components fit together.*

| File | What it does | Key words |
|------|-------------|-----------|
| `moduleWirer.md` | Verify modules are correctly wired — imports, exports, call chains | module wiring, imports, exports, call chain, verify |
| `moduleOrchestrator.md` | Design how modules interact and depend on each other | module design, orchestration, dependencies, interfaces |
| `architectureReview.md` | Review system-level design decisions | architecture, design review, system design |
| `systemDesign.md` | Design a system from scratch before building | system design, architecture, scalability, design from scratch |

---

## Documentation

*Write docs that people actually read and use.*

| File | What it does | Key words |
|------|-------------|-----------|
| `documentationWriter.md` | Technical reference and API docs | API docs, reference, technical writing |
| `userDocWriter.md` | User-facing how-tos, quickstarts, guides | user docs, how-to, quickstart, guide, tutorials |
| `changelogWriter.md` | Maintain a useful changelog for users | changelog, release notes, versioning, semver |

---

## Research

*Investigate, evaluate, and synthesize — verify don't assume.*

| File | What it does | Key words |
|------|-------------|-----------|
| `researchBrief.md` | Structured research before writing anything | research, investigation, brief |
| `webResearch.md` | Web search, source evaluation, synthesis | web search, sources, citations, evaluate |
| `codebaseResearch.md` | Understand an unfamiliar codebase quickly | codebase,陌生的 code, understand, orientation |
| `securityResearch.md` | CVE lookup, threat modeling, defensive tools | CVE, vulnerability, threat model, security research |
| `technologyResearch.md` | Evaluate tools for a go/no-go decision | evaluate, tool comparison, A vs B, decision |

---

## Workflows & Operations

*Reliable processes for complex or recurring tasks.*

| File | What it does | Key words |
|------|-------------|-----------|
| `workflow.md` | General task workflow template — the fallback | workflow, task template, process |
| `migrationAssistant.md` | Plan database and system migrations | migration, database migration, schema migration |
| `incidentPostmortem.md` | Structured post-mortem after production incidents | incident, postmortem, outage, retrospective |
| `featureFlags.md` | Design and manage feature flags safely | feature flags, rollout, kill switch, A/B test |
| `secretsManagement.md` | API keys, env vars, rotation, leakage prevention | secrets, API keys, env vars, .env, rotation |

---

## API Design

*Design APIs that are intuitive, consistent, and hard to misuse.*

| File | What it does | Key words |
|------|-------------|-----------|
| `apiDesign.md` | REST/WebSocket APIs — request shapes, error format, auth | REST, WebSocket, API design, endpoints, error format, versioning |

---

## Git & Code Review

*Commit messages that help, PR reviews that catch issues.*

| File | What it does | Key words |
|------|-------------|-----------|
| `gitCommitMsg.md` | Conventional commits — scoped, meaningful, blame-friendly | git, commit, conventional commits, changelog |
| `prReview.md` | Methodical PR review before approving | pull request, code review, PR review, approve |

---

## Image Generation

*Get the right image in fewer attempts — no wasted generations.*

| File | What it does | Key words |
|------|-------------|-----------|
| `imagePromptWriter.md` | Write prompts that match what you want — reference analysis, no over-specification | image gen, AI art, prompt, prompt writing, Midjourney, DALL-E |
| `promptRefiner.md` | Fix vague prompts iteratively — narrow to exact result | vague prompt, refine, fix prompt, iterate |

---

## Adversarial & Failure Testing

*Find bugs by proving code breaks, not that it works.*

| File | What it does | Key words |
|------|-------------|-----------|
| `adversarialTester.md` | Tests that pass when code fails — prove the breakage | adversarial, fail-fast, property-based, fuzzing |
