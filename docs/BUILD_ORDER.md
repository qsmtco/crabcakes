# Build Order — Coder Enhancement Roadmap

**Date:** 2026-05-08
**Author:** Qaster
**Status:** ACTIVE — Agreed build order for Coder agent improvements

## Source Documents

All source documents live in `/home/q/projects/crabcakes/docs/`:

| File | What It Is |
|------|-----------|
| `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` | Master plan — 28 improvements across 7 domains (prompt engineering, context assembly, tool enhancements, conversation management, observability) |
| `ENFORCEMENT_LAYER_SPEC.md` | Deep-dive implementation spec for post-write verification (runtime enforcement — syntax, tests, lint checks) |

This file (`BUILD_ORDER.md`) is the **agreed execution order** — the single source of truth for what to build and when. It supersedes the phase numbering in both source documents.

---

## Recommended Build Order

### Phase 1: Prompt Engineering ✅ DONE

**What:** Rewrite system prompts and tool descriptions to give Coder a comprehensive engineering methodology.

**Source:** `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` §4.1, §4.2, §4.3, §4.14, §4.16, §4.18

**Completed items:**
- ✅ Rewrote `prompts/system/coder.md` — full engineering agent prompt (Core Principles, Workflow, Code Quality, Tool Strategy, Error Recovery, Architecture Respect, Anti-Patterns)
- ✅ Enhanced tool descriptions in `agent/tools.py` — all 7 tools now have WHEN TO USE / WHEN NOT TO USE / BEHAVIOR / COMMON PATTERNS
- ✅ Stripped `prompts/system/default.md` to bare identity + tools + format (removed duplicate guidelines)
- ✅ Deleted dead `CODER_PROMPT_TEMPLATE` from `agent/special_agents.py`
- ✅ Added `CRABCAKES_PROMPT_DEBUG` env var to `utils/prompt_loader.py`
- ✅ Removed duplicate identity statement from `coder.md` (no longer says "You are a senior software engineer" — `default.md` handles identity)

**Estimated:** 4-6 hours (completed)

---

### Phase 2: `edit_file` Tool ✅ DONE

**What:** Add a targeted edit tool that replaces exact text in files, instead of requiring full file rewrites. This is the single highest-impact tool change — full file rewrites are the #1 source of subtle bugs in AI-generated code.

**Source:** `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` §4.11

**Why before enforcement:** The enforcement layer (Phase 3) triggers on file modification. If we build enforcement first with only `write_file`, then add `edit_file` later, we have to go back and wire enforcement into a second tool. Building `edit_file` first means enforcement targets "file modification" (both tools) from day one.

**Completed items:**
- ✅ `_edit_file()` function in `agent/tools.py` — exact text replacement, unique match required, sandboxed
- ✅ `edit_file` ToolDefinition with full WHEN TO USE / WHEN NOT TO USE / BEHAVIOR / IMPORTANT / COMMON PATTERNS
- ✅ Added to Coder's tool list in `agent/special_agents.py`
- ✅ Added `### edit_file` guidance to `prompts/system/coder.md` Tool Strategy section
- ✅ 36 tests passing (existing suite)
- ✅ `ARCHITECTURE.md` updated (4 locations)

**Estimated:** 3-4 hours (completed)

---

### Phase 3: Enforcement Layer (Phases A-D) ✅ DONE

**What:** Automatic post-write verification that runs syntax checks, tests, and lint after every file modification — regardless of whether the model remembers to verify. This replaces the prompt-based verification guidance (§4.6/4.7) with runtime enforcement.

**Source:** `ENFORCEMENT_LAYER_SPEC.md` — Phases A through D

**Why here:** With `edit_file` in place, enforcement can target both `write_file` and `edit_file` from the start. No retrofitting needed.

**Scope (from enforcement spec):**
- Phase A: Core infrastructure — `agent/enforcement.py` stub, `EnforcementConfig`, wiring into `agent/runtime.py` tool loop, `on_enforcement_status` callback
- Phase B: Tier 1 — Syntax guard (`py_compile`, `node --check`, etc.) after every file write
- Phase C: Tier 2 — Test runner (detect framework, find related tests, run them) after every source file write
- Phase D: Tier 3 — Lint check (detect linter, run on changed file) after every source file write

**NOT in this phase (deferred):**
- Phase E: Stuck detection — better to build after seeing enforcement in practice
- Phase F: Per-language configuration — polish item

**Relationship to Enhancement Proposal:** This *replaces* §4.6 (Plan-Execute-Verify prompt), §4.7 (Error Recovery prompt), and §4.8 (Max Iterations Intelligence) with stronger runtime enforcement. Those sections of the proposal are considered superseded by the enforcement spec.

**Estimated:** 5-7 hours

---

### Phase 4: Context Assembly

**What:** Improve what context the model sees when starting a task. Currently gets a static directory tree — should always include project docs and prioritize relevance.

**Source:** `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` §4.4a, §4.5

**Scope:**
- §4.4a (Quick Win): Always include `.crabcakes/` docs (architecture.md, requirements.md, context.md, tasks.md) in file context — these are small and always relevant
- §4.5: Add token budget awareness — explicit allocation (system prompt / conversation / tool results) with smart truncation (keep head + tail, drop middle)

**Note:** §4.4b (query-aware file retrieval) is deferred — that's a larger effort (8+ hours) and the quick win covers the main gap.

**Status:** ✅ Done

**What was implemented:**

**§4.4a — .crabcakes/ docs always included (context.py):**
- New `_read_crabcakes_docs()` helper in `agent/context.py` — reads all nine standard docs (`architecture.md` through `project.md`) from the project `.crabcakes/` directory.
- `build_file_context()` now prepends these docs under a ``## Project docs`` header, before the directory tree, so the agent always sees project docs first in every file context.
- `_load_crabcakes_doc()` helper exposed for `prompt_loader` if it needs individual doc access in the future.

**§4.10 — Summary on trim (conversation.py):**
- New `_last_exchange_summary()` method on `Conversation` — scans the user messages in the trimmed portion, builds a compact numbered list of task descriptions (capped at 5, 100 chars each).
- `trim_to_token_limit()` now calls `_last_exchange_summary()` after every trim operation. When the conversation is long enough (8+ messages remaining) and there are user messages to summarize, a summary message is injected as an assistant turn at position `len-4` — just before the preserved tail.
- This prevents the model from losing context of what was accomplished in exchanges that were removed to stay under the token budget.

**Estimated:** 1-2 hours (§4.4a); 6-8 hours (§4.10 — conversation management was in Phase 5 but closely related to §4.10, so handled here)

---

### Phase 5: Conversation Management

**What:** Better handling of long conversations — graduated compaction instead of crude oldest-first removal, and context summaries when messages are trimmed.

**Source:** `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` §4.9, §4.10

**Why here:** Matters more as sessions get longer. Current Coder sessions are short, so this is important but not urgent. After enforcement is running, sessions will naturally get longer (model self-corrects more), making this more relevant.

**Scope:**
- §4.9: Graduated compaction — 3-tier strategy: snip (truncate long tool outputs), compress (replace old exchanges with summaries), drop (remove oldest)
- §4.10: Summary on trim — inject compressed summary when messages are removed so model doesn't lose context

**Note:** §4.10 is now implemented (see Phase 4 above). §4.9 (snip/compress/drop tiers) remains.

**Estimated:** 3-4 hours (§4.9 remaining after §4.10)

---

### Phase 6: Polish & Observability

**What:** Quality-of-life improvements for debugging and monitoring.

**Source:** `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` §4.12, §4.13, §4.15

**Scope:**
- §4.12: Enhanced `grep_code` tool — symbol search, import graph queries, reference finding (stretch goal)
- §4.13: Improved `exec_command` output — separate stdout/stderr, explicit exit code, specific failure lines for test failures
- §4.15: Token budget logging — per-turn breakdown of system prompt / conversation / tool result token counts

**Estimated:** 3-5 hours

---

### Phase 7: Stuck Detection & Per-Project Config

**What:** Intelligence for detecting when Coder is spinning its wheels, and per-project enforcement configuration.

**Source:** `ENFORCEMENT_LAYER_SPEC.md` Phases E and F

**Why last:** Stuck detection needs real-world data to calibrate thresholds. Better to observe how Coder behaves with enforcement enabled (Phase 3) before building pattern detection on top of it.

**Scope:**
- Phase E: Stuck detection — detect repeated tool calls (same tool + args, 3+ times), detect write-heavy loops (8+ writes without verification), inject intervention messages
- Phase F: Per-project enforcement configuration (`.crabcakes/enforcement.json`)

**Estimated:** 3-4 hours

---

## Summary

| Phase | What | Source Document | Source Section(s) | Status | Est. Time |
|-------|------|----------------|-------------------|--------|-----------|
| 1 | Prompt engineering | Enhancement Proposal | §4.1, §4.2, §4.3, §4.14, §4.16, §4.18 | ✅ Done | 4-6h |
| 2 | `edit_file` tool | Enhancement Proposal | §4.11 | ✅ Done | 3-4h |
| 3 | Enforcement layer (A-D) | Enforcement Spec | Phases A-D | ✅ Done | 5-7h |
| 4 | Context assembly | Enhancement Proposal | §4.4a, §4.10 | ✅ Done | 1-2h |
| 5 | Conversation management (§4.9 remaining) | Enhancement Proposal | §4.9 | 🔲 Next | 3-4h |
| 6 | Polish & observability | Enhancement Proposal | §4.12, §4.13, §4.15 | 🔲 Pending | 3-5h |
| 7 | Stuck detection + config | Enforcement Spec | Phases E-F | 🔲 Pending | 3-4h |

**Total estimated remaining:** 21-34 hours

---

## Key Design Decision

The Enhancement Proposal originally designed verification as prompt engineering ("tell the model to verify"). The Enforcement Spec replaces this with runtime enforcement ("make the model verify"). The following Enhancement Proposal sections are **superseded** by the Enforcement Layer Spec:

- §4.6 (Plan-Execute-Verify Loop) → replaced by enforcement runtime
- §4.7 (Error Recovery) → replaced by enforcement stuck detection + auto-verification
- §4.8 (Max Iterations Intelligence) → replaced by enforcement stuck detection

These sections should remain in the Enhancement Proposal for historical context but are not implemented separately.

---

*Last updated: 2026-05-08 by Qaster*
