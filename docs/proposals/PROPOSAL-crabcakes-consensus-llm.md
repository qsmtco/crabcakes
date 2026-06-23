# PROPOSAL: Crabcakes Consensus LLM

**Status:** Preliminary — idea-bouncing phase, not yet scoped for implementation.  
**Author:** Qaster  
**Date:** 2026-06-22  
**Priority:** TBD — back-burner for now  
**Inspired by:** `agent/kb_server.py` (existing local HTTP server that mimics OpenAI's `/v1/chat/completions` and uses an external LLM for synthesis).

---

## One-liner

A local stdlib HTTP server that **looks like a single OpenAI-compatible provider** to crabcakes, but **behind the scenes uses three different vendor LLMs** — one as synthesizer/orchestrator, two as independent answerers — and returns a blended answer.

---

## Motivation

- **Vendor resilience.** If one provider rate-limits or goes down, the user doesn't notice.
- **Bias reduction.** Two independent answers get blended, reducing single-vendor blind spots.
- **Generalizes a proven pattern.** `agent/kb_server.py` already proved this architecture works (KB lookup → optional synthesis → graceful fallback). This proposal just generalizes "synthesis" from "rewrite these chunks" to "rewrite the consensus of two answers."

---

## Architecture

```
┌──────────────┐
│  crabcakes   │  sees ONE provider ("crabcakes")
│   runtime    │
└──────┬───────┘
       │  POST /v1/chat/completions  (standard OpenAI shape)
       ▼
┌──────────────────────────────────────────────┐
│  Local HTTP server (stdlib http.server)      │
│  proposed: providers/crabcakes_llm_server.py │
├──────────────────────────────────────────────┤
│  Synthesizer LLM (vendor A)                  │
│   1. Receive question                        │
│   2. Light cleanup (typos, grammar)          │
│   3. Fan out cleaned prompt in parallel ──┐  │
│   4. Wait for both answers               │  │
│   5. Blend answers                       │  │
│   6. Return as OpenAI-shaped response    │  │
└────────────────────────────────────────┼──┘
                                         │
              ┌──────────────────────────┴──────────────────┐
              ▼                                             ▼
   ┌──────────────────┐                          ┌──────────────────┐
   │ Answerer LLM #1  │                          │ Answerer LLM #2  │
   │ (vendor B)       │                          │ (vendor C)       │
   │ OpenAI / Anthropic│                         │ Google / xAI / … │
   └──────────────────┘                          └──────────────────┘
```

All three vendors **must be different companies**.

---

## Flow

1. Caller sends a chat-completions request to the local server.
2. Synthesizer (vendor A) receives it.
3. Synthesizer **lightly cleans up the prompt** — fixes spelling, grammar, and other trivial clarifying edits. Does NOT paraphrase intent or change meaning.
4. Synthesizer **fans the cleaned prompt out in parallel** to both answerer LLMs.
5. Synthesizer waits for both responses (with timeouts).
6. Synthesizer **blends both answers into one final answer.**
7. Server returns the synthesized answer as a standard OpenAI-shaped response.

### Answerer prompts
- Both answerers receive the **same cleaned question** (not tailored per answerer).
- Each produces its answer independently.

### Failure modes
- **Both answerers fail** → server returns a 5xx / error response.
- **One answerer fails** → server returns the surviving answer **as-is**, plus a warning header/note (e.g. `"X-CrabCakes-Consensus-Warning: only one LLM succeeded"`).
- **Synthesizer fails** → server returns 5xx (cannot blend).

---

## Public surface

Standard OpenAI `/v1/chat/completions` shape, served on a local port (likely `18791` to stay adjacent to kb_server's `18790`).

Crabcakes registers it as a provider like any other — no runtime changes needed.

---

## Configuration

**To be decided, but minimum viable options:**

- `CRABCAKES_CONSENSUS_SYNTHESIZER_URL` + auth (env)
- `CRABCAKES_CONSENSUS_ANSWERER_1_URL` + auth (env)
- `CRABCAKES_CONSENSUS_ANSWERER_2_URL` + auth (env)
- `CRABCAKES_CONSENSUS_SYNTHESIS_TIMEOUT` (seconds, default ~3.0)
- `CRABCAKES_CONSENSUS_ENABLED` (default `1`, `0` to disable and short-circuit to one answerer)
- Optional UI hook into the existing settings panel.

---

## Open questions / known concerns

These were raised during the idea-bouncing phase and need resolution before serious implementation:

1. **Latency floor.** Total request time ≈ `max(answerer1, answerer2) + synthesizer`. For interactive chat this could feel slow. **Streaming the synthesizer's final response is the likely fix.**
2. **Cost = 3–4× per request** (two answerers + two synthesizer calls — one for cleanup, one for blend). Trade-off: combine the synthesizer's two jobs into one call to save tokens, but loses the prompt cleanup step.
3. **Consensus ≠ correctness.** Two LLMs can confidently agree on a wrong answer. Documentation should be honest about this — "crabcakes LLM" is a blend, not a truth oracle.
4. **Synthesizer is a single point of failure** for orchestration. Should be the most reliable vendor (uptime > cleverness).
5. **Debugging weird syntheses.** Need a "raw" passthrough mode (e.g. `X-CrabCakes-Raw: 1` header) that returns both answerer responses concatenated, with delimiters, for inspection.
6. **Naming.** `crabcakes LLM` is fuzzy. Candidates: `consensus_server.py`, `ensemble_server.py`, `crabcakes_llm_server.py`.
7. **Where does it live?** `agent/kb_server.py` lives in `agent/` because it serves the agent. This is a **provider**, not an agent — suggests `providers/` directory (keep providers/ separate from agent/).
8. **Token accounting / logging.** Every request should log: which answerers succeeded, token counts (per answerer + synthesizer), synthesis time. Needed the first time someone says "why was that answer wrong?"

---

## Milestones (very rough, for when we come back to this)

- **M0 — Spike (~1 day):** hardcoded 3 vendors, no config, prove the OpenAI-shape response works end-to-end with one crabcakes agent.
- **M1 — Configurability:** env vars for all 3 endpoints + auth + timeouts. Streaming of the final response.
- **M2 — Robustness:** raw passthrough mode, per-request structured logging, partial-failure warning header.
- **M3 — UX integration:** settings panel UI for picking vendors; docs for users explaining the trade-offs.
- **M4 — Production hardening:** rate limiting, retry policy, cost caps, opt-in per-agent (don't force consensus on every model).

---

## Status

Deferred to back-burner. Come back to this when:

- The current provider list is stable and well-tested.
- We have a real-world case where vendor diversity would have saved the user time.
- The kb_server pattern has been extended/improved enough that we know what the failure modes look like.

Do NOT start implementation until M0 is approved with a written decision on the **3 concrete must-haves**:

1. Streaming strategy for the synthesized response.
2. "Raw" passthrough mode for debugging.
3. Config schema (env var minimum).

---

## Related

- `agent/kb_server.py` — the inspiration; same architecture pattern (local stdlib server, OpenAI shape, optional external synthesis).
- `agent/kb_lookup.py` — sibling lookup module, useful precedent for caching/lazy-loading.
- `utils/providers_store.py` — provider configuration storage; may be reusable for the config schema.