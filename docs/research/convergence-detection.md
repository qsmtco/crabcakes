# Agent Conversation Convergence Detection

> **Status: OBSOLETE** — Convergence detection was built as a standalone module but is now dead code (nothing imports it). The `stoplight-summary.md` documents what was built. `test_convergence.py` has 5 failing tests for dead code.

**Date:** 2026-04-19
**Status:** Research — pre-spec
**Context:** Part of agent collaboration system for CrabCakes
**Problem:** LLMs always respond. How do you know when a multi-agent conversation is naturally done?

---

## The Problem

LLMs are completion engines — they always produce output. There is no native "no response needed" instinct. Two agents will talk forever: "thanks" → "you're welcome" → "let me know if you need anything" → "will do" → infinity. This is an unsolved problem in multi-agent AI.

**Existing approaches (all flawed):**
- AutoGen: 12+ termination condition types (max messages, keyword detection, timeout, token usage). None detect natural conversation end. All are brute force.
- CrewAI: max_iterations per task. Cuts off whether done or not.
- LangChain: max_iterations + early_stopping_method. Same problem.
- Academic research: MALLM paper observed natural convergence patterns but didn't implement detection.
- Everyone treats termination as a failure mode to guard against. Nobody treats it as a natural lifecycle to detect.

## The Approach: Convergence Detection

Borrow from numerical analysis and signal processing. When solving equations or training neural networks, you watch for convergence — values stop changing, error stops shrinking. Apply the same concept to conversation signals.

**Core principle:** Default is "stop after 3 exchanges." Math can extend by 1 if it detects active work. Each extension must be earned.

## Five Signals

### 1. Response Length Decay (RLD)
- Ratio of current response tokens to previous response tokens
- Healthy conversation: roughly constant or growing
- Dying conversation: shrinking with each exchange
- Compute: `current_tokens / max(previous_tokens, 1)`
- Normalize to 0-1

### 2. Semantic Novelty (SN)
- How much new information is in this response vs everything said before
- Compute via Jaccard distance of n-grams against rolling summary of previous responses
- Or use embedding cosine distance (more accurate, more expensive)
- New info = high novelty = still working
- Repeating/confirming = low novelty = converging
- Range: 0 to 1

### 3. Perplexity (PPL)
- How "surprised" the model was by its own output
- Requires log probabilities from API (OpenAI provides, Anthropic does not)
- High perplexity = agent exploring, uncertain = still working
- Low perplexity = agent confident, predictable = wrapping up
- "Found a race condition, investigating further" → high perplexity
- "Confirmed, fix applied, tests passing" → low perplexity
- Range: 1 to ∞, normalize to 0-1
- **Fallback:** If API doesn't provide logprobs, redistribute weight to other signals

### 4. Entropy Score (H)
- Shannon entropy of word frequency distribution within a single response
- Information-dense responses: high entropy (many different words, low repetition)
- Closing responses: low entropy ("yes done confirmed looks good" — few distinct words, high repetition)
- Different from novelty: entropy measures internal diversity of one response; novelty measures diversity against previous responses
- Range: normalize to 0-1

### 5. Question Density (QD)
- Count of questions in response divided by total sentences
- Questions = open threads = still working
- No questions = closure = wrapping up
- Compute: regex for ? marks + question-starting words (how, why, what, where, when, could, would, should)
- Range: 0 to 1

## The Convergence Equation

```
C = α·norm(RLD) + β·(1 - SN) + γ·(1 - norm(PPL)) + δ·(1 - QD) + ε·(1 - H)

C = 1 → fully converged (stop)
C = 0 → still actively working (continue)
```

## Suggested Weights

| Signal | Symbol | Weight | Rationale |
|--------|--------|--------|-----------|
| Semantic Novelty | β | 0.30 | Strongest signal — directly measures new information |
| Response Length | α | 0.25 | Reliable, easy to compute, almost always decays at end |
| Perplexity | γ | 0.20 | Powerful but not available from all APIs |
| Entropy | ε | 0.15 | Catches low-information closing responses |
| Question Density | δ | 0.10 | Simple but noisy — agents sometimes ask closing questions |

## Decision Rules

```
if exchange_count <= 2:
    continue                    # always let first 3 exchanges happen (question, answer, ack)
elif C >= 0.75:
    stop                        # converged — conversation is done
elif C >= 0.55:
    extend_by_1                 # borderline — allow one more exchange, re-evaluate
else:
    continue                    # still actively working

Hard cap: 10 exchanges. No exceptions. Pull-the-plug limit.
```

## Why This Is Robust

- **Short but novel response:** "Found it — it's not auth, it's the connection pool" → length says done, but novelty and entropy say not done. C stays low. Correct behavior.
- **Long but repetitive response:** "As I mentioned before, the issue is... and I want to reiterate..." → length looks healthy, but novelty ≈ 0, entropy low. C spikes. Correct behavior.
- **Genuine politeness loop:** "Thanks!" → "You're welcome!" → "Let me know" → all signals low. C ≥ 0.75 after exchange 3. Stop. Correct behavior.
- **Deep debugging session:** Responses stay high-novelty, high-entropy, with questions. C stays below 0.55. Extends naturally. Correct behavior.

## What This Doesn't Solve

- How agents communicate (routing, shared context) — separate problem
- Whether agents should be allowed to communicate at all — PM policy decision
- Budget/cost management — orthogonal concern
- Context injection — how agents see each other's work — separate problem

## Implementation Notes

- All five signals can be computed from response text + metadata (token counts, logprobs if available)
- No external model calls needed (no separate LLM to evaluate convergence)
- Entropy and novelty use standard NLP/math — no dependencies beyond what CrabCakes already has
- Perplexity requires logprobs from API — graceful fallback if unavailable
- Computation cost per evaluation: negligible (sub-millisecond for all five signals)

## Academic Context

- **Information Theory (Shannon, 1948):** Entropy and perplexity fundamentals
- **Numerical Analysis:** Convergence detection in iterative methods
- **Signal Processing:** Energy detection — measuring when signal amplitude drops below threshold
- **NLP:** n-gram overlap, Jaccard distance, embedding similarity — standard tools
- **MALLM paper (arxiv 2410.22932, 2024):** Observed that multi-agent systems "discuss more difficult examples for longer until they reach a consensus" — natural convergence observed but not implemented as detection

## Status As Far As We Know

This approach — convergence detection via weighted signal combination applied to multi-agent conversation termination — appears to be novel. Extensive search found no existing implementation. Everyone else uses hard limits, keyword detection, or semantic loop detection. Nobody measures natural conversation wind-down as a positive signal.

---

*This document covers only the convergence detection mechanism. Agent routing, shared context, and collaboration architecture are separate concerns documented elsewhere.*
