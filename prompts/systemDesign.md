# System Design

Design a system before building it. Avoids expensive rewrites, forces you to think about failure modes, and gives others a chance to review your thinking before you invest time coding.

---

## Before You Start

1. What does success look like? (functional requirements)
2. What are the non-functional requirements? (latency, availability, throughput, cost)
3. Who's the user? (internal ops, end users, other services)
4. What's the scale? (10 users or 10M users, changes the architecture entirely)
5. What's the time budget? (prototype vs production)

---

## Design Layers

Work from the outside in:

```
[User] → [API/Gateway] → [Application] → [Storage] → [Cache]
```

For each layer, decide:
- What does it do?
- How does it fail?
- How does it scale?
- What's the data model?

---

## Decision Checklist

### API / Gateway

- [ ] REST vs WebSocket vs gRPC — which fits the use case?
- [ ] Versioning strategy — URL path or headers?
- [ ] Auth — API keys, OAuth2, JWT? Where does validation happen?
- [ ] Rate limiting — who enforces it?
- [ ] Request/response shape — consistent error format?
- [ ] Pagination — cursor or offset?

### Application / Business Logic

- [ ] Stateless or stateful? (stateless scales easier)
- [ ] Sync or async processing? (async = faster responses but complex)
- [ ] Background jobs — where do they run? (queue + workers, cron, serverless)
- [ ] Idempotency — can the same request be safely retried?

### Data / Storage

- [ ] Relational vs NoSQL vs Object storage vs Time-series?
- [ ] Read replicas for horizontal scaling?
- [ ] What data needs to be consistent vs available?
- [ ] How is data backed up? How often? How tested?
- [ ] What's the retention policy?

### Caching

- [ ] What gets cached? (expensive computations, hot data)
- [ ] Cache invalidation — how and when?
- [ ] Single instance or distributed? (Redis vs in-memory)
- [ ] What happens when the cache is cold?

### Resilience

- [ ] What single points of failure exist?
- [ ] What happens when each dependency goes down?
- [ ] Circuit breakers — which calls need them?
- [ ] Retry strategy — exponential backoff with jitter?
- [ ] Graceful degradation — what can the system do when degraded?

### Security

- [ ] Authentication and authorization — who can do what?
- [ ] Encryption at rest? In transit?
- [ ] Input validation — where?
- [ ] Audit logging — what events matter?
- [ ] Secrets management — where do API keys live?

---

## Capacity Planning

| Question | How to estimate |
|----------|----------------|
| Requests per second | Current traffic × growth factor |
| Storage needed | Daily data × retention days |
| Cache size | Hot data set size × items per request |
| Database connections | Concurrent users × connections per user |
| CDN bandwidth | Asset size × daily views |

---

## Design Document Template

```markdown
# System Design: [Project Name]

## Overview
[1–2 sentence description of what this system does]

## Goals
### Functional
- [ ] Feature A
- [ ] Feature B

### Non-Functional
- **Latency:** < Xms p99
- **Availability:** 99.9% uptime
- **Throughput:** X concurrent users
- **Scale:** X million users / day

## Architecture

### High-Level
[ASCII diagram or description of major components]

### Data Flow
[How a request flows through the system]

### Data Model
[Key entities and their relationships]

## Design Decisions

### API Design
[Chosen approach + alternatives considered + why]

### Storage
[Chosen approach + alternatives considered + why]

### Caching
[What, where, how invalidated]

### Failure Modes
| Component fails | Impact | Mitigation |
|----------------|--------|------------|
| Database | ... | ... |
| Cache | ... | ... |
| Queue | ... | ... |

## Open Questions
[Any unresolved design decisions or known risks]

## TODO Before Building
[Things to research or decide before implementation]
```

---

## Common Trade-offs

| If you choose | You're trading off |
|--------------|-------------------|
| Consistency over availability | User sees stale data sometimes |
| SQL over NoSQL | Less flexible schema, harder to horizontally scale |
| Sync processing | Simplicity over resilience |
| Monolith | Simplicity over deployment independence |
| Event-driven | Loose coupling over traceability |
| Distributed system | Scale over operational complexity |

---

## When to Stop

Design until:
- You can explain it to a skeptical colleague
- The failure modes are understood and acceptable
- The non-functional requirements are met
- The data model is stable

Stop when:
- You're debating whether to use PostgreSQL or MySQL (both work, pick one)
- You're designing features no one asked for
- You're optimizing before measuring

---

## Activation

Proceed with designing a system for: [describe the problem to be solved]
