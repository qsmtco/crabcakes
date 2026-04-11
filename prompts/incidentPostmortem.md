# Incident Postmortem

Write a structured post-mortem after every significant incident. The goal: understand what happened, why, and how to prevent it from happening again — without blame.

---

## Golden Rules

1. **Blame the system, not the person.** People make mistakes in systems that were designed to allow mistakes.
2. **Document what happened, not who's fault it is.** "The deploy script deleted the wrong table" is a fact. "Dev X was careless" is not.
3. **Every major incident gets a post-mortem.** Minor incidents can be combined.
4. **Action items must have owners and deadlines.** A post-mortem without action items is theater.

---

## Timeline Template

| Time (UTC) | Event |
|-----------|-------|
| HH:MM | Alert fired — page received by on-call |
| HH:MM | On-call acknowledged |
| HH:MM | Root cause identified |
| HH:MM | Fix deployed |
| HH:MM | Service restored |
| HH:MM | Post-mortem started |

Build this from logs, chat history, and监控 dashboards — not memory.

---

## Post-Mortem Template

```markdown
# Incident Postmortem: [Short Descriptive Title]

**Date:** YYYY-MM-DD
**Duration:** X hours Y minutes
**Severity:** P0 / P1 / P2 / P3
**Status:** Post-mortem complete

## Summary
[2–3 sentences: what happened, impact, what we did about it]

## Impact
- Users affected: [number or "all users of X"]
- Revenue impact: [if applicable]
- Downtime duration: [start → end]
- Services affected: [list]

## Root Cause
[One paragraph: the actual technical cause. Be specific.
 Not "a configuration error" but "the database connection pool
 was set to 10 connections but the app required 50 under
 normal load, causing connection exhaustion after a deploy."]

## Timeline
[Timeline table from above]

## Detection
How did we find out?
- [ ] Automated alert: [what triggered]
- [ ] Customer report: [how it reached us]
- [ ] Internal monitoring: [what caught it]

**Time to detect (MTTD):** X minutes
**Time to resolve (MTTR):** Y minutes

## Contributing Factors
[What made this worse or harder to detect]
- Factor 1
- Factor 2

## Action Items

| Action | Owner | Due date | Status |
|--------|-------|----------|--------|
| Increase connection pool from 10 to 50 | @dev | 2024-02-01 | Done |
| Add alert when connection pool > 80% | @sre | 2024-02-01 | In progress |
| Document failover procedure | @ops | 2024-02-05 | Not started |

## What Went Well
- Alerting caught it within 2 minutes
- Runbook was accurate and helpful
- Communication to affected users was clear

## What Could Be Improved
- No automated rollback — had to manually redeploy
- Runbook missing the specific command to check connection pool

## Lessons Learned
[Any broader takeaways from this incident]
```

---

## Severity Definitions

| Severity | What it means |
|----------|---------------|
| P0 | Complete service outage, revenue impact, data loss risk |
| P1 | Major feature broken for all users, partial outage |
| P2 | Feature broken for subset of users, workaround exists |
| P3 | Minor issue, no user impact, cosmetic |

---

## Action Item Rules

Every action item must have:
1. **Specific owner** — not "the team", a person
2. **Due date** — within 2 weeks for most items
3. **Verified completion** — closed by the owner, not assumed done

If an action item isn't done, it needs a follow-up post-mortem to understand why and reprioritize.

---

## What to Avoid

| Bad practice | Why | Good practice |
|-------------|-----|--------------|
| "Human error" | Useless, blamey | "The system allowed this human error to happen" |
| "We should have monitoring" | Vague | "Add alert for X when Y exceeds Z threshold" |
| No action items | Theater post-mortem | 3–5 concrete, owned, dated items |
| Waiting weeks to write it | Memory fades | Within 48 hours of resolution |

---

## Activation

Proceed with writing a post-mortem for: [describe the incident, or say "generate a template for a future incident"]
