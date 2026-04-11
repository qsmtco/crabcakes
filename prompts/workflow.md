# Software Development Workflow

## Starting a New Project

```
1. researchBrief.md
   ↓
   Lightweight research — 1-2 pages max. What problem? Who has it?
   Answers 3 questions: What, Why, What could go wrong.
   DO NOT write implementation details or project plans here.

2. fullStackGenerator.md
   ↓
   Generate the COMPLETE application — wired, entry point included.
   This prevents orphan modules.

3. codeTester.md
   ↓
   Add tests that verify happy paths work.
   This confirms it does what you asked.

4. adversarialTester.md
   ↓
   Add tests that try to BREAK it.
   This finds bugs before users do.

5. securityAudit.md
   ↓
   Hunt for vulnerabilities.
   This catches injection, auth issues, data leaks.

6. errorHandlingReview.md
   ↓
   Find silent failures and unhandled edge cases.
   This makes the app resilient.

7. codeRefactor.md
   ↓
   Clean up the generated code.
   This makes it maintainable.

8. documentationWriter.md
   ↓
   Generate README, API docs, runbooks.
   This so you remember how to run it later.
```

## Quick Feature / PR Workflow

```
fullStackGenerator.md → codeTester.md → adversarialTester.md
```

## Before Each Development Session

```
PERIODIC DESIGN CHECKS:
  architectureReview.md

ADD NEW FEATURES:
  fullStackGenerator.md
  codeTester.md
  adversarialTester.md

PERIODIC SECURITY PASS:
  securityAudit.md
```

## Reference — All Available Prompts

| Phase | Prompt | Purpose |
|-------|--------|---------|
| Research | `researchBrief.md` | Lightweight pre-work — 1-2 pages max |
| Design | `architectureReview.md` | Define architecture before coding |
| Generate | `fullStackGenerator.md` | Wired, runnable code |
| Verify | `codeTester.md` | Happy path tests |
| Break | `adversarialTester.md` | Bug-finding tests |
| Harden | `securityAudit.md` | Vulnerability scan |
| Resilience | `errorHandlingReview.md` | Edge cases, silent failures |
| Clean | `codeRefactor.md` | Improve without changing behavior |
| Document | `documentationWriter.md` | README, API docs, runbooks |
| Audit | `codeAuditGeneral.md` | General-purpose code quality review |
| Audit | `codeAudit1.md` | Phase 1 audit — structure, patterns |
| Audit | `codeAudit2.md` | Phase 2 audit — deeper analysis |
| Audit | `accessibilityAudit.md` | Accessibility compliance |
| Debug | `bugFinder.md` | Systematic bug finding |
| Debug | `adversarialDebugger.md` | Attack assumptions to find bugs |
| Debug | `incidentDebugger.md` | Production issue, diagnose from logs |
| Debug | `codeDebugger.md` | Elite debugging methodology |
| Module | `moduleOrchestrator.md` | Existing project has unwired modules |
| Module | `moduleWirer.md` | Modules exist but aren't connected |
| Performance | `performanceOptimizer.md` | App is slow, find bottlenecks |
| Dependencies | `dependencyAudit.md` | Check package health/vulnerabilities |
| Data | `dataModeling.md` | Design data models and schemas |
| SQL | `sqlWriter.md` | Write SQL queries and migrations |
| API | `apiDesign.md` | Design REST/GraphQL APIs |
| System | `systemDesign.md` | Large-scale system architecture |
| Web | `webResearch.md` | Research libraries, tools, services |
| Migration | `migrationAssistant.md` | Moving to new language/framework |
| Testing | `testDataGenerator.md` | Need fuzzed/edge case test fixtures |
| Incident | `incidentPostmortem.md` | Post-incident analysis and blameless review |
| Security | `securityResearch.md` | Deep-dive security research |
| Change | `changelogWriter.md` | Generate changelogs from git history |
| Feature | `featureFlags.md` | Design and implement feature flags |
| Docker | `dockerWriter.md` | Write Dockerfiles and docker-compose |
| Git | `gitCommitMsg.md` | Generate conventional commit messages |
| Review | `prReview.md` | Code review coaching |
| Image | `imagePromptWriter.md` | Write prompts for image generation models |
| Prompt | `promptRefiner.md` | Refine and improve prompts |

## Other Useful Prompts

| Prompt | Use when |
|--------|----------|
| `codebaseResearch.md` | Exploring an unfamiliar codebase |
| `technologyResearch.md` | Evaluating tech stacks and tools |
| `loadTesting.md` | Capacity and load testing plans |
| `secretsManagement.md` | Secure handling of credentials and keys |

---

**Tip:** Run `bugFinder.md` before `adversarialTester.md` — bugFinder focuses on code-level defects, adversarialTester on behavioral/contract violations. They complement each other.
