# Web Research

Search, evaluate, and synthesize information from the web. Don't trust any single source. Don't cite the model — cite the source.

---

## Before You Start

1. Clarify what you need to know — be specific
2. Identify 3–5 search terms that cover different angles
3. Set a time budget — research for 5–10 minutes, then synthesize

---

## Search Strategy

| What | Where | Notes |
|------|-------|-------|
| Fresh news | Brave Search (web_search) | Set `freshness: "month"` or `"week"` |
| Specific docs | Direct URL (web_fetch) | If you know the doc, fetch it directly |
| API details | Official docs or GitHub | Often more accurate than summaries |
| Opinions/discussion | Hacker News, Reddit | Good for "what's the community sentiment" |
| Vulnerabilities | CVE databases, NVD, Exploit-DB | For security research |

---

## Source Evaluation Checklist

For every source you consider citing:

- [ ] Is this primary source or someone's summary of a source?
- [ ] Is the date recent enough for the topic? (tech changes fast — 2023 may be obsolete)
- [ ] Is this a vendor marketing page? (they have incentives to exaggerate)
- [ ] Is this from a site with a known bias?
- [ ] Can you cross-reference with one other independent source?

---

## Synthesis Rules

1. **Paraphrase everything.** Never quote verbatim unless it's a precise technical spec.
2. **State the consensus.** "Most sources agree X, but Y argues Z."
3. **State the disagreement.** "There is conflicting information about whether A or B."
4. **Flag confidence.** "X is well-established fact" vs "Y is speculative"
5. **Cite inline.** Not footnotes — inline: `[source]`, `[source 1][source 2]`.

---

## Output Format

```
## Research Question
[One sentence restating what we're investigating]

## Summary
[2–3 sentence executive summary of findings]

## Key Findings

### Finding 1: [Title]
**What:** [What the sources say]
**Source:** [URL or "multiple sources"]
**Confidence:** High / Medium / Low

### Finding 2: [Title]
...

## Conflicting Information
[Any sources that disagree and why]

## Open Questions
[What the research didn't answer]

## Recommended Next Step
[What to do with this information]
```

---

## Common Pitfalls

| Pitfall | Why it's bad | Fix |
|---------|--------------|-----|
| Citing model knowledge as fact | Training data may be wrong or outdated | Always verify with web search |
| Reading only one source | Can be wrong or biased | Check 2–3 independent sources |
| Going too deep | Endless research, no output | Set a time limit and synthesize |
| Ignoring the date | Old info on fast-moving topics | Always check publication date |
| Accepting vendor claims at face value | Vendors exaggerate benefits | Look for independent benchmarks/reviews |

---

## Activation

Proceed with researching: [state the research question]
