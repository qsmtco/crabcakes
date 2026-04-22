# Stoplight — Conversation Convergence for Multi-Agent AI Systems

## What We Built

A system that tells a multi-agent AI conversation when to stop. Not when to give up, not when to crash — when the work is actually done.

## The Problem

When multiple AI agents collaborate — one writes code, another reviews it, a third tests it — they go back and forth. Sometimes three turns. Sometimes thirty. How do you know when to pull the plug?

Most systems don't solve this at all. They just set a hard limit — "after 10 rounds, stop" — which means you're either cutting off real work or letting conversations run forever. Some look for magic words like "TERMINATE" — which only works if humans manually add them. Nobody has built a system that actually *reads the room*.

The difficulty is that conversations are nothing like each other. A three-turn "thanks, that worked" looks nothing like a twenty-turn debugging marathon. The same three signals that mean "done" in one conversation mean "keep going" in another. The model has to learn all of these patterns at once, and it has to do it without any single obvious signal.

## How We Solved It

We studied 266 real multi-agent conversations — short ones, long ones, successful ones, messy ones — and taught a machine to spot the difference between a conversation that's winding down and one that's just getting started.

We identified 10 signals that good conversations share:
- Whether the last response is shorter than usual (a sign of wrapping up)
- Whether the conversation has circled back to words it started with (a conversation that returns to its beginning is usually done)
- How varied the language is throughout
- Whether the topic is still shifting or has settled
- And several others that capture the structure and flow of a healthy handoff

Then we trained a Random Forest — a type of machine learning model that asks dozens of yes/no questions in sequence — to weigh all 10 signals at once and reach a verdict. Think of it like a team of experienced engineers each checking one thing, then voting. The model doesn't just guess randomly — it has seen hundreds of real examples and learned the patterns that separate "done" from "keep going."

## Why Our Method Is Better

We run at **99.1% accuracy** with no cloud dependency, no GPU, no latency. The model trains once and runs instantly on any machine. It's small and explainable — we know exactly which signals matter most, and we can trace every decision back to a reason. It works across wildly different conversation types and lengths because it learned from real examples rather than hard-coded rules.

Most multi-agent frameworks (AutoGen, CrewAI, LangGraph) sidestep this problem entirely. They either set arbitrary turn limits, look for magic keywords, or require a human to manually interrupt. We built the thing nobody else bothered to build.

## The Numbers

- **536** test conversations evaluated
- **531** correct decisions
- **5** failures — all by design (the QAC rule: a complete exchange needs at least three turns before it can end, so very short conversations that should stop are allowed to continue)
- **99.1%** accuracy overall

## Technical Details

- **Model**: Random Forest (200 trees)
- **Features**: 10 hand-crafted signals trained on 266 labeled conversation fixtures
- **Threshold**: P(stop) >= 0.50 to stop
- **Speed**: Runs instantly with no external API calls or GPU required
- **Deployment**: Drop-in module — import and use anywhere
