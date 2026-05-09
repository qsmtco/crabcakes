# Research: How Major Coding Agents Handle the Write→Test→Verify Loop

**Date:** 2026-05-07
**Context:** Captain JAQx asked how the "big time" coding agents enforce the write→test→verify feedback loop at runtime, and whether crabCakes should implement its own enforcement layer. This document captures findings from researching OpenAI Codex, Devin, OpenHands/OpenDevin, SWE-agent, Aider, and academic work on runtime enforcement.

---

## The Question

When an AI coding agent writes code, what forces it to verify that code works? Is there a runtime hook that auto-triggers tests after a file write? Or does every agent just rely on the LLM "deciding" to run tests?

---

## TL;DR — Nobody Enforces It

**None of the major coding agents enforce the write→test→verify loop at the runtime level.** Every agent relies on some combination of:
1. System prompts that *suggest* running tests
2. Rich environments (tests exist, linters exist, CI exists) so error messages naturally guide the model
3. The underlying LLM being smart enough to follow through on testing after writing

The "tight feedback loop" is **emergent**, not enforced.

---

## Agent-by-Agent Breakdown

### OpenAI Codex

**Source:** OpenAI blog post "Unrolling the Codex Agent Loop" (https://openai.com/index/unrolling-the-codex-agent-loop/) + open-source repo at https://github.com/openai/codex

**Architecture:**
- The "Codex harness" is a shared Rust library (Codex core) that runs the agent loop, thread lifecycle, config/auth, and sandboxed tool execution
- All surfaces (CLI, web, VS Code, macOS app) share the same harness
- Uses OpenAI's Responses API for inference

**The agent loop (simplified):**
1. Build prompt from conversation state
2. Send to Responses API, receive SSE stream
3. If model requests a tool call → execute it → append result to prompt
4. Re-query model with updated prompt
5. Repeat until model emits a final assistant message (no tool calls)

**Enforcement:**
- **None.** The harness is a pure orchestrator. It executes whatever tool calls the model requests, in order.
- The system prompt (stored in markdown files like `gpt-5.2-codex_prompt.md`) tells the model to run tests, but there's no structural enforcement.
- The shell tool is sandboxed (can't write outside designated directories), but that's security, not methodology.

**Key insight from OpenAI's own Codex best practices page:**
> "Ask it to create tests when needed, run the relevant checks, confirm the result, and review the work before you accept it. Codex can do this loop for you, but only if it knows what 'good' looks like."

Translation: *the user has to tell it what good looks like.* The runtime doesn't enforce it.

**Prompt caching strategy (notable):**
- Static content (instructions, tools) goes first in the prompt
- Variable content goes last
- Mid-conversation config changes are appended, not inserted, to preserve cache hits
- This is a performance optimization, not a correctness one

**Context window management:**
- Uses a `/responses/compact` endpoint that returns an opaque `encrypted_content` blob encoding the model's latent understanding
- Richer than text summarization, preserves reasoning quality
- Auto-triggers when token count exceeds `auto_compact_limit`

---

### Devin (Cognition)

**Source:** Devin's "Coding Agents 101" guide (https://devin.ai/agents101)

**Architecture:**
- Fully autonomous: plans, codes, tests, delivers as PRs
- Has a "Planner" module that breaks down tasks before writing code
- Operates in its own remote development environment with full shell access

**Enforcement:**
- **None at the runtime level.** Devin relies on environmental richness.
- Their own guidance emphasizes: give the agent CI, tests, type checkers, linters, and it will naturally iterate against error messages.

**Key quote from Devin's guide:**
> "Much of the magic of agents comes from their ability to fix their own mistakes and iterate against error messages. Providing strong feedback loops through tools like type checkers, linters, and unit tests greatly enhances their performance."

**Devin's strategy for large tasks:**
1. Co-develop a PRD (plan first)
2. Set checkpoints: Plan → Implement chunk → Test → Fix → Checkpoint review → Next chunk
3. Use defensive prompting (tell it where to start, what to watch out for)
4. Start fresh when the agent is going in circles

**Key weakness they acknowledge:**
> "Bugs reports can be deceptively simple. We recommend asking for a list of probable root causes rather than trying to debug and fix everything itself."

---

### OpenHands (formerly OpenDevin)

**Source:** OpenHands V1 SDK paper (arXiv 2511.03690), deep dive at https://dev.to/truongpx396/openhands-deep-dive-build-your-own-guide-1al0, source at https://github.com/All-Hands-AI/OpenHands

**Architecture:**
- Scored ~77% on SWE-Bench Verified with Claude Sonnet 4.5
- Core: Agent (stateless) → Conversation (loop runner, state) → Workspace (executes actions) → EventLog (append-only)
- Agent is a pure function: `history → next Action`. No state of its own.
- Event log is the single source of truth — replaying it reconstructs the entire conversation

**The agent loop (canonical 30 lines):**
```python
def step(self, conversation, on_event, on_token=None):
    state = conversation.state
    # 1. Drain pending confirmed actions
    pending = ConversationState.get_unmatched_actions(state.events)
    if pending: self._execute_actions(conversation, pending, on_event); return
    # 2. Check hooks that might block user message
    # 3. Build LLM prompt (condenser may summarize)
    msgs_or_cond = prepare_llm_messages(state.events, condenser=self.condenser, llm=self.llm)
    # 4. Call LLM with retry
    response = make_llm_completion(self.llm, msgs_or_cond, tools=...)
    # 5. Classify and dispatch: tool_call → execute, content → emit, empty → retry
```

**The CodeAct philosophy:**
Instead of giving the LLM 20 bespoke tools each with their own JSON schema, give it **bash, Python, and a browser DSL**, and let it express anything as code. Empirically generalizes far better and reduces parsing errors.

**Enforcement:**
- **None for write→test→verify.** But OpenHands has the best architectural pattern for it:
- **"Observations close the loop"** — every error, stderr, exit code, and HTTP response goes back into the next prompt. Self-correction is not a feature — it's a *side effect* of letting the LLM see its own consequences.
- **Stuck detection** — a subsystem that detects when the agent is going in circles and intervenes. But it's detection, not prevention.

**Example trace from OpenHands docs (fixing a failing test):**
```
Step 0: SystemPromptEvent(prompt=..., tools=[...])
Step 1: MessageEvent(content="Find the failing test and fix it")
Step 2: ActionEvent(CmdRunAction(command="pytest -x"))
Step 3: ObservationEvent(CmdOutputObservation(stdout="...FAILED...", exit_code=1))
Step 4: ActionEvent(CmdRunAction(command="cat tests/test_auth.py"))
Step 5: ObservationEvent(stdout="...assert user.token == 'abc'...")
Step 6: ActionEvent(FileEditAction(path="src/auth.py", str_replace=...))
Step 7: ObservationEvent(FileEditObservation(diff="..."))
Step 8: ActionEvent(CmdRunAction(command="pytest -x"))    ← verification!
Step 9: ObservationEvent(stdout="...1 passed", exit_code=0))  ← green!
Step 10: ActionEvent(AgentFinishAction(final_thought="Fixed..."))
```
Note: Steps 8-9 are verification, but they happen because the LLM decided to do them, not because the runtime forced it.

**V1 design principles (worth stealing):**
1. Optional isolation, not mandatory sandboxing (swap LocalWorkspace ↔ DockerWorkspace)
2. Stateless components, single source of truth (only ConversationState is mutable)
3. Strict separation of concerns (SDK never imports applications)
4. Two-layer composability (package level + component level)

---

### SWE-agent (Princeton)

**Source:** https://github.com/SWE-agent/SWE-agent, NeurIPS 2024 paper

**Architecture:**
- Takes a GitHub issue and tries to fix it autonomously
- Gives the agent a shell with guardrails (can't edit outside repo, can't escape sandbox)
- Uses "Agent-Computer Interfaces" — custom shell commands that constrain what the agent can do

**Enforcement:**
- **None for the test loop.** The agent has an `edit` command with guardrails to protect against self-inclicted cascading edit errors, but no write→test enforcement.
- The system prompt tells the agent to run tests, but it's advisory.

---

### Aider

**Source:** https://github.com/Aider-AI/aider, read editblock_prompts.py directly

**Architecture:**
- Pair programming in terminal — user describes changes, aider proposes SEARCH/REPLACE blocks
- Not fully autonomous — user approves each edit
- Supports multiple models (Claude, GPT, etc.)

**Enforcement:**
- **None.** Aider is interactive, not autonomous. The user is the enforcement layer.
- The system prompt explicitly says: "Think step-by-step and explain the needed changes" and gives detailed formatting rules for SEARCH/REPLACE blocks
- Testing is the user's responsibility

**Notable prompt pattern (from editblock_prompts.py):**
```
Act as an expert software developer.
Always use best practices when coding.
Respect and use existing conventions, libraries, etc that are already present in the code base.
Take requests for changes to the supplied code.
If the request is ambiguous, ask questions.
```

---

### Claude Code

**Source:** Piebald-AI/claude-code-system-prompts repo, system prompt analysis blog posts

**Architecture:**
- Uses sub-agents (Plan, Explore, Task, General Purpose) for different work modes
- General-purpose agent prompt: "Complete the task fully — don't gold-plate, but don't leave it half-done"
- Has 24 built-in tool descriptions

**Enforcement:**
- **None at runtime.** Pure prompt-driven.
- The general-purpose agent prompt says: "For file searches: search broadly when you don't know where something lives. Use Read when you know the specific file path."
- Has a `update_plan` tool for tracking multi-step work

---

### AgentSpec (Academic — Runtime Enforcement)

**Source:** "AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents" (arXiv 2503.18666, March 2025)

**What it is:**
A domain-specific language (DSL) for specifying and enforcing runtime constraints on LLM agents. The only research we found that actually proposes structural enforcement.

**How it works:**
```
rule @inspect_transfer
  trigger Transfer
  check !is_to_family_member
  enforce user_inspection
end
```

Rules have three parts:
1. **Trigger** — what event activates the rule (e.g., "file write", "shell command")
2. **Predicate** — condition to check (e.g., "amount > threshold", "file is sensitive")
3. **Enforcement** — what to do (user_inspection, action_termination, self_reflection, corrective_invocation)

**Results:**
- Prevented unsafe code execution in 90%+ of cases
- Eliminated all hazardous actions in embodied agent tasks
- 100% compliance in autonomous vehicle scenarios
- Computationally lightweight (milliseconds overhead)

**Status:** Academic research. Not deployed in any major coding agent. The big players haven't adopted it.

**Why it matters for crabCakes:** This is the closest thing to what we were imagining — a rule engine that intercepts tool calls and enforces constraints. The pattern could be adapted:
```
rule @verify_after_write
  trigger write_file
  check true  # always enforce
  enforce inject_message("You wrote a file. Verify it before continuing.")
end
```

---

## What crabCakes Has Today

### Current Architecture
- **Tool loop:** Same as everyone else — LLM calls tools, runtime executes, results go back, repeat
- **Max iterations:** 50 (configurable via `max_tool_iterations` in `agent/config.py`)
- **No forced verification:** After `write_file`, nothing auto-triggers tests
- **No checkpoint gating:** The model can write a file, say "Done!", and the loop ends
- **No stuck detection:** No subsystem detects when the agent is going in circles

### What the New coder.md Prompt Asks For (But Doesn't Enforce)
- "Run tests after modifications"
- "Small, verified steps — never write more than ~50 lines without testing"
- "Verify after every change"
- "Run the linter if configured"

All of these are suggestions. The model can ignore them.

### What Could Be Added (Ranked by Impact)

**1. Post-write system message injection (easy, high impact)**
After every `write_file` tool call, inject a system-level message into the conversation:
> "File written. Before continuing, verify this change by running relevant tests."

This is the AgentSpec pattern, implemented as a simple tool-result decorator. It doesn't force the model to test, but it makes the instruction present in the conversation context at the exact moment it matters.

**2. Stuck detection (medium effort, medium impact)**
Track the last N tool calls. If the agent calls the same tool with similar args 3+ times, inject a message: "You appear to be stuck. Re-read the file and reconsider your approach."

OpenHands does this. It catches the most common failure mode (agent going in circles).

**3. Auto-test trigger (hard, highest impact but controversial)**
After `write_file`, automatically run `exec_command("pytest {related_test_file}")` and inject the result into the conversation before the model's next turn.

This is the tightest possible loop — but it's also the most opinionated. What if there are no tests? What if the tests take 5 minutes? What if the write was to a config file with no related test?

**4. Iteration budget per file (medium effort, good guardrail)**
Track how many tool iterations are spent on a single file. If the agent spends more than N iterations on one file without progress, surface a warning or stop.

---

## Key Takeaways

1. **Everyone relies on the prompt, not the runtime.** No major coding agent structurally enforces write→test→verify.

2. **The real enforcement is environmental.** If tests exist and the model can run them, error messages naturally guide iteration. The loop works because of *observations closing the loop* (OpenHands pattern), not because of runtime hooks.

3. **M2.7 is capable enough.** With a good prompt (which coder.md now is) and a project that has tests, the model should naturally iterate.

4. **The gap isn't enforcement — it's test existence.** If a project has no tests, no amount of enforcement helps. The highest-ROI improvement is making sure projects have test suites the Coder can run.

5. **If crabCakes wants to be first to enforce this, the AgentSpec pattern is the way.** A lightweight rule engine that intercepts tool calls and injects messages or blocks actions. Novel but feasible.

---

## OpenClaw's Architecture (For Context)

OpenClaw (the platform I run on) is a general-purpose agent framework, not a coding-specific one. It provides:
- Tool loop with read/write/exec/web/browser/cron/sessions/subagents
- Sub-agent spawning for isolated work
- Cron jobs for scheduled tasks
- OpenClaw PRISM for security hooks (message ingress, tool execution, etc.)

But there's no coding-specific enforcement layer. When I write code, nothing forces me to test it either.

---

## Sources

- OpenAI Codex agent loop: https://openai.com/index/unrolling-the-codex-agent-loop/
- OpenAI Codex source: https://github.com/openai/codex
- Codex best practices: https://developers.openai.com/codex/learn/best-practices
- Devin Agents 101: https://devin.ai/agents101
- OpenHands V1 SDK paper: arXiv 2511.03690
- OpenHands deep dive: https://dev.to/truongpx396/openhands-deep-dive-build-your-own-guide-1al0
- OpenHands source: https://github.com/All-Hands-AI/OpenHands
- SWE-agent: https://github.com/SWE-agent/SWE-agent (NeurIPS 2024)
- Aider source: https://github.com/Aider-AI/aider
- Claude Code system prompts: https://github.com/Piebald-AI/claude-code-system-prompts
- AgentSpec (runtime enforcement DSL): arXiv 2503.18666
- OpenClaw PRISM: arXiv 2603.11853
