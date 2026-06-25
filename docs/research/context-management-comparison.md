# Context Management Capability Comparison

> CrabCakes vs. the most sophisticated small projects on GitHub
> Generated: 2026-06-25

---

## Head-to-Head Matrix

| Capability | CrabCakes | agent-context-system | ACE (FCA) | agents-md | Context-Engine-AI |
|-----------|-----------|---------------------|-----------|-----------|-------------------|
| Budget-aware system prompt | ✅ 15% of CX | ❌ | ✅ 40-60% target | ❌ | ❌ |
| Smart truncation with invariants | ✅ Core files kept | ✅ 9:1 compression | ❌ | ❌ | ❌ |
| Token-accurate counting | ✅ tiktoken + cache | ❌ chars only | ❌ | ❌ | ❌ |
| Summary-on-trim | ✅ Budget-aware | ✅ Consolidation phase | ✅ Compaction | ❌ | ❌ |
| KV cache / latent briefing | ❌ | ❌ | ❌ | ❌ | ❌ |
| Mid-conversation compaction | ❌ | ✅ Auto-consolidation | ✅ FCA protocol | ❌ | ❌ |
| Byte-cap output control | ❌ | ❌ | ❌ | ✅ `head -c 4000` | ❌ |
| Semantic file partial reads | ❌ | ❌ | ❌ | ❌ | ✅ MCP symbol graph |
| Self-improvement loop | ✅ 5-layer stack | ❌ | ❌ | ❌ | ❌ |
| Untrusted-data fences | ✅ | ❌ | ❌ | ❌ | ❌ |
| Multi-agent context coordination | ❌ | ❌ | ❌ | ❌ | ❌ |
| Offline-first / zero deps | ❌ (needs tiktoken) | ✅ Zero deps | ❌ | ✅ | ❌ |

---

## CrabCakes Strengths vs. the Field

These are things CrabCakes does **better** than any of the hidden gems:

1. **Self-improvement stack (5 layers)** — No other project comes close. Bug journal → project rules → enforcement → structured feedback → dream consolidation. This is a *learning system*, not just a context manager.

2. **Untrusted-data fences** — The `<untrusted-project-data>` pattern is a real defense against prompt injection from cloned repos. No other project has this.

3. **Security enforcement (CRIT-1/2)** — Binary allowlist + env scrubbing + audit log. No other project has this level of subprocess security.

4. **KB with fallback chain** — Local embedding → LLM synthesis → fallback to cloud model. No other project has a 3-tier knowledge retrieval system.

5. **Token estimation with caching** — Tiktoken accuracy without the performance penalty. Most projects use chars÷4.

6. **Model context auto-discovery** — `/v1/models` probe to auto-fill UI. Just shipped.

---

## Where the Hidden Gems Win

These are things other projects do **better** than CrabCakes:

1. **Mid-conversation compaction** (FCA, agent-context-system) — CrabCakes only deletes old messages. Others rewrite/consolidate into denser forms.

2. **Byte-cap output control** (agents-md) — CrabCakes truncates tool output by lines. One huge line still floods context.

3. **Semantic file partial reads** (Context-Engine-AI) — CrabCakes reads entire files. Others read only the relevant symbol.

4. **Multi-agent context coordination** (ContextOptimizer) — CrabCakes agents each have independent context. Others share context surfaces.

5. **Offline-first / zero deps** (agent-context-system, agents-md) — CrabCakes needs tiktoken. Others work with stdlib only.

---

## Ranked Steal List

| Priority | Capability | Source | Effort | Impact |
|----------|-----------|--------|--------|--------|
| 🔴 1 | Mid-conversation compaction | FCA / agent-context-system | High | Massive — closes the #1 gap |
| 🔴 2 | Byte-cap output control | agents-md | Low (5 lines) | High — prevents context flood |
| 🔴 3 | Dynamic budget fraction | CrabCakes own analysis | Low | Medium — adaptive budget |
| 🟡 4 | Context pressure signal | Novel | Medium | Medium — proactive warnings |
| 🟡 5 | Semantic file partial reads | Context-Engine-AI | High | High — but needs tree-sitter |
| 🟡 6 | Multi-agent context dedup | ContextOptimizer | High | Medium — only matters with N agents |
| 🟢 7 | KV cache for static prompts | Provider-dependent | Medium | Medium — needs provider support |
| 🟢 8 | Dream consolidation (SPEC-4) | CrabCakes own spec | Medium | Low — process, not context |

---

## The Frontier: What Nobody Has

These are capabilities that **no project** (including CrabCakes) has implemented:

1. **KV cache / latent briefing** — Pre-compile static prompt sections into KV cache entries. Nobody does this at the application level.

2. **Multi-agent context coordination** — Shared context surface per project, per task, per agent-team. Only ContextOptimizer attempts this.

3. **Context-as-a-service** — Context management as a separate microservice that agents connect to. Only Context-Engine MCP approaches this.

4. **Adaptive context learning** — The system learns over time which context patterns lead to success and adjusts retrieval/retention accordingly. This is the dream consolidation vision (SPEC-4).

5. **Cross-conversation context transfer** — When a new conversation starts, pull relevant context from past conversations on the same project. Only agentic-context-engine approaches this.
