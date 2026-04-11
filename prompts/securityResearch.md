# Security Research

Research a security topic: vulnerability, attack vector, tool, or defensive technique. Security claims require evidence. Threats must be assessed by likelihood AND impact.

---

## Research Scope

Define before you start:

1. **Threat actor:** Who is the attacker? (insider, external, nation-state, script kiddie)
2. **Attack surface:** What can they reach? (network, physical, supply chain)
3. **Likelihood:** How easy is this to exploit?
4. **Impact:** What happens if they succeed? (data breach, DoS, RCE)

---

## Search Strategy

| Source | What it gives you |
|--------|-------------------|
| CVE / NVD | Vulnerability details, CVSS scores, affected versions |
| CISA KEV | Actively exploited vulnerabilities (more urgent than CVE alone) |
| OWASP | Web application attack patterns |
| MITRE ATT&CK | Known attacker tactics and techniques |
| Exploit-DB / PacketStorm | Working exploit code |
| vendor advisories | Authoritative fix information |
| security blogs (Troy Hunt, Krebs, Schearer) | In-depth analysis |
| GitHub Advisories | Code-level vulnerability info for open source |

---

## Vulnerability Assessment

For each vulnerability:

| Field | What to determine |
|-------|-------------------|
| CVE | Exact CVE identifier |
| CVSS Score | 0–10 severity |
| CVSS Vector | What specifically is affected (AV, AC, PR, UI) |
| Affected versions | Exact version range |
| Fixed version | First version with patch |
| Exploitability | Is working exploit code public? Is it weaponized? |
|Detection | How do you know if you've been hit? |

---

## Defensive Research

For each defensive technique or tool:

1. What attack does it defend against?
2. What does it NOT defend against?
3. How is it bypassed? (known bypasses?)
4. What are the prerequisites? (must be running, must have network access, etc.)
5. How do you verify it's working?
6. What does a successful deployment look like vs a failed one?

---

## Threat Modeling Template

```
## Threat: [Name]

### Attacker Profile
- **Who:** [threat actor]
- **Goal:** [what they want]
- **Capability:** [skill level, resources]

### Attack Path
[Step-by-step path from initial access to impact]

### Likelihood
[Low / Medium / High] — [reason]

### Impact
[Low / Medium / High] — [data breach / downtime / RCE / etc.]

### Existing Defenses
- [Defense 1]: [effective against what]
- [Defense 2]: [effective against what]

### Gaps
[Any missing controls]

### Recommended Mitigations
[Practical steps, prioritized by impact vs effort]
```

---

## Output Rules

1. **Cite CVEs, not "there's a vulnerability in X"** — give the exact ID
2. **Distinguish CVSS from actual risk** — CVSS 9.8 with no public exploit ≠ urgent
3. **Distinguish severity from impact** — a DoS on a test server ≠ critical
4. **Always give a fix or mitigation** — research without a path forward is anxiety, not research
5. **Flag if information is incomplete or uncertain** — "CVSS unknown", "exploit code unconfirmed"

---

## Common Pitfalls

| Pitfall | Why it's bad | Fix |
|---------|--------------|-----|
| CVSS theater | Citing high CVSS without checking if it's actually exploitable | Verify with exploit code or reliable analysis |
| Threat inflation | Treating theoretical risks as imminent | Assess likelihood, not just severity |
| Ignoring actively exploited vulns | CISA KEV exists for a reason | Always check KEV first |
| Recommending tools you haven't verified | Security tools break things | Test before recommending |
| Forgetting the basics | Fancy EDR while passwords are "admin" | Check MFA, patching, least privilege first |

---

## Activation

Proceed with security research on: [vulnerability name / attack vector / tool / system]
