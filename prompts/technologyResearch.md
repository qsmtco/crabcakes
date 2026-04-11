# Technology Research

Research a technology, tool, library, or platform to make an informed decision. Not "what is it" — "should we use it, and if so, how."

---

## Research Question

Before researching, clarify:

1. **What decision are we trying to make?** (adopt vs not, A vs B, upgrade vs stay)
2. **What criteria matter?** (performance, cost, community, security, license, support)
3. **What's the time budget?** (5-min scan vs 2-hour deep dive)

---

## Evaluation Criteria (apply selectively)

| Criteria | Questions to answer |
|----------|---------------------|
| **Maturity** | How old? Stable API? Breaking changes frequent? |
| **Community** | Active development? How many contributors? GitHub stars / PyPI downloads? |
| **Security** | Known CVEs? Audited? Security policy? |
| **License** | Permissive or restrictive? Commercial use allowed? |
| **Performance** | Benchmarks? Memory footprint? Cold start time? |
| **Reliability** | Uptime track record? SLA? Incident history? |
| **Support** | Paid support available? Community forums? Response time? |
| **Lock-in** | How hard to migrate away? Portability? |
| **Cost** | Direct cost (licensing) + indirect (infra requirements, learning curve) |

---

## Source Priority

| Source type | Weight | Notes |
|-------------|--------|-------|
| Official docs | High | What they say about themselves |
| Independent benchmarks | High | Not vendor-created |
| User reviews | Medium | G2, Capterra, Trustpilot — signal vs noise |
| Community sentiment | Medium | Hacker News, Reddit — good for "what are people frustrated with" |
| GitHub issues | High | Real bugs, real complaints |
| Security advisories | High | For any dependency |

---

## Competitive Analysis Template

For comparing A vs B vs C:

```
## Technology Comparison: [A vs B vs C]

### [A]
**What it is:** [one sentence]
**License:** [X] | **Stars/Downloads:** [N] | **Last release:** [date]
**Strengths:** [what it's genuinely good at]
**Weaknesses:** [documented problems, known limitations]
**Security:** [CVEs, audit history]
**Verdict:** [for teams/size/context]

### [B]
...

### [C]
...

## Decision Matrix

| Criteria | Weight | [A] | [B] | [C] |
|----------|--------|-----|-----|-----|
| Maturity | 20% | | | |
| Security | 25% | | | |
| Performance | 15% | | | |
| Community | 10% | | | |
| License | 10% | | | |
| Support | 10% | | | |
| Ease of migration | 10% | | | |
| **Weighted total** | 100% | **X** | **Y** | **Z** |

## Recommendation
[Winner with rationale — be specific about which use cases favor which]
```

---

## Quick Tech Scan (5 minutes)

When you just need the basics:

1. Find the official site and read the one-sentence description
2. Check GitHub: stars, last commit, open issues, PRs
3. Search "[tool] alternatives" — competitors reveal the design space
4. Search "[tool] problems" or "[tool] sucks" — community frustration is informative
5. Check the license
6. Form a preliminary opinion and flag if more research is needed

---

## Deep Dive (30+ minutes)

When the decision is high-stakes:

1. Read the official docs start to finish (or significant portion)
2. Run the quick start — get it running yourself
3. Read 3–5 real user reviews (not the 5-star or 1-star extremes)
4. Search for incident post-mortems if it's infrastructure-critical
5. Look at the GitHub issue queue — are there many unresolved bugs?
6. Check if the maintainer has given talks or written about design decisions
7. Make a recommendation with explicit trade-offs

---

## Common Pitfalls

| Pitfall | Why it's bad | Fix |
|---------|--------------|-----|
| Vendor marketing as research | Exaggerates benefits, hides costs | Always cross-reference with independent sources |
| Ignoring license | "Free" can mean "viral GPL" | Check before adopting |
| "Everyone uses X" | Herd mentality | Evaluate on merits |
| Avoiding tech because it's new | Missing better solutions | Evaluate maturity vs fit for purpose |
| Ignoring migration cost | Low adoption cost ≠ low total cost | Factor in learning curve and porting effort |

---

## Output Format

```
## Research Question
[What decision are we making?]

## Summary
[2-3 sentence recommendation with key rationale]

## [Technology A]
**License:** X | **Maturity:** Y | **Community:** N active contributors
**Strengths:** [...]
**Weaknesses:** [...]
**Verdict:** [use when / don't use when]

## [Technology B]
...

## Recommendation
[Explicit recommendation with criteria and trade-offs]
```

---

## Activation

Proceed with researching: [technology or decision to investigate]
