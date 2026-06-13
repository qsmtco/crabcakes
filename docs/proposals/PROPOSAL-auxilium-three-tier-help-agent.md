# PROPOSAL: Auxilium — Three-Tier Help Agent

**Date:** 2026-06-13
**Author:** Qaster
**Supersedes:** `PROPOSAL-crabcakes-always-on-help-agent.md` (2026-05-30)
**Status:** Proposal — pending Captain approval
**Priority:** High
**Effort:** ~3-4 weeks across all three tiers (Tier 1 shippable in ~1 week)

> **Status (verified 2026-06-13):** ⚠️ **DRAFT — pending review**
> **status:** `DRAFT`
>
> The original help-agent PROPOSAL (2026-05-30) shipped a partial implementation: the agent exists, auto-opens, and is auto-added to projects — but the "works out of the box with zero config" promise was never kept. The current `auxilium.yaml` (renamed from `crabcakes.yaml` in commit `3721792`) has `provider: openrouter` and no built-in key, so a fresh-install user opens Auxilium and gets `RuntimeError: no provider configured`. This proposal replaces the original with a three-tier, KB-first architecture.

---

## Why

### The Problem (still true, six weeks later)

A fresh-install user opens CrabCakes, sees the Auxilium 🦀 tab auto-open, types "hi" — and gets a runtime error because no LLM provider is configured. The helper agent is the *first* thing a new user interacts with and the *most* important one to work without configuration. Today it does neither.

The original PROPOSAL promised a built-in Google Gemini API key so the agent "works out of the box, no signup, no API keys, no gateway." That key was never provisioned. The SPEC's AC-7 ("load_agent_config() includes `providers.google`] when user hasn't configured one") is not implemented. The dependency on an external free-tier LLM made the "out of the box" promise fragile and undeliverable.

### The Solution

**Stop trying to ship a built-in LLM. Ship a built-in knowledge base instead.**

Auxilium becomes a **three-tier help agent** whose primary answer engine is a local knowledge base indexed by a local embedding model. No external LLM is required for the most common question types. An LLM (the user's configured provider, or a free fallback) is layered on top only when the KB can't answer.

The three tiers, in priority order:

1. **Tier 1 — First-run setup** (most important): get CrabCakes set up for the user. Verify install, walk through gateway connection, configure a provider, smoke-test.
2. **Tier 2 — Help assistant**: explain all CrabCakes features, configuration, commands, agents. "How do I…" questions.
3. **Tier 3 — Power user**: get the most out of using CrabCakes. Workflow patterns, customization, multi-agent strategies.

### Why now

- The user just renamed the agent from Crabcakes to Auxilium (commit `3721792`). The rename is the right moment to revisit scope.
- `sentence-transformers 5.4.1`, `torch 2.11.0+cu130`, and `numpy 2.4.3` are all installed on the dev machine. The local-embedding-model architecture is buildable today.
- The existing knowledge base (7 files, 412 lines, ~13KB) is a stub. It needs ~5-10× expansion to be a real answer engine, but the indexing layer can be built and tested against the stub, then the KB can be expanded incrementally.
- The Captain has confirmed the scope shape (Tier 1 → Tier 2 → Tier 3) and the KB-first / LLM-second phasing in conversation 2026-06-13.

---

## What

### Before (current state, after commit `3721792`)

```yaml
# prompts/default_agents/auxilium.yaml
name: Auxilium
role: helper
provider: openrouter       # ← requires user config
model: openrouter/free     # ← requires user config
api_key_built_in: false    # ← no built-in key
auto_open: true
auto_add_to_projects: true
```

Fresh install with empty `~/.config/crabcakes/agent.json`:
1. App launches ✓
2. Auxilium tab auto-opens ✓
3. User types anything → `RuntimeError: no provider configured` ✗
4. User has no recourse within the app

The agent *exists* but doesn't *work* in the scenario it's designed for.

### After (proposed)

```
┌──────────────────────────────────────────────────────────────────┐
│ Tier 1: First-run setup (always works, no LLM, no network)       │
│   • Install verification (platform, Python, GTK4, deps)          │
│   • Gateway connection walkthrough                              │
│   • Provider configuration (static 3-button picker, no LLM)     │
│   • Smoke test                                                  │
├──────────────────────────────────────────────────────────────────┤
│ Tier 2: Help assistant (KB-only, no LLM)                        │
│   • Feature walkthroughs    → knowledge/features.md             │
│   • Configuration reference → knowledge/configuration.md        │
│   • Agent questions         → knowledge/agents.md               │
│   • Commands reference      → knowledge/commands.md             │
│   • Troubleshooting basics  → knowledge/troubleshooting.md      │
├──────────────────────────────────────────────────────────────────┤
│ Tier 3: Power user (KB + LLM, requires configured provider)     │
│   • Workflow patterns, customization, multi-agent advice        │
│   • Beyond-KB questions, opinionated recommendations            │
│   • Brain upgrade: LLM is used for synthesis + reasoning        │
└──────────────────────────────────────────────────────────────────┘
```

The architectural rule: **KB lookup is always the first step. The LLM is always optional. The architecture degrades gracefully if the LLM tier changes.**

| State | Provider | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| Fresh install | None | ✓ Static wizard | ✓ KB raw chunks | ✗ "Configure a provider for power-user answers" |
| Configured (OpenRouter/Ollama) | Cloud free or local | ✓ Static wizard | ✓ KB + LLM synthesis | ✓ Full LLM |
| Configured (OpenAI/Anthropic) | Cloud paid | ✓ Static wizard | ✓ KB + LLM synthesis | ✓ Full LLM, best quality |

### The "brain upgrade" is real and continuous

You said: *"the helper agent first uses a knowledge base in a local embedding model and then once the user is able to input an API key the helper agent's brain is upgraded."*

Refined: the upgrade is **a phase boundary, not a one-time event.** The state machine:

- **Phase 1 — KB-only:** no LLM. Static first-run wizard for Tier 1, KB chunk retrieval for Tier 2. Tier 3 returns a graceful "configure a provider for this kind of question" message. **This is the only mode that's truly "out of the box."**
- **Phase 2 — KB + LLM synthesis:** user has configured any provider. KB lookup is still the first step (so answers stay grounded in docs), but retrieved chunks are handed to the LLM with a "synthesize this" prompt. Friendly, conversational, still correct. **This is the "brain upgrade" you described.**
- **Phase 3 — KB + LLM + general reasoning:** the LLM is no longer constrained to retrieved chunks. It can answer Tier 3 questions, give opinions, compare approaches. **This is what a real assistant does.** Gated on "user has a configured provider."

The architecture supports all three. The user experience at any point is "the best Auxilium I can be given what's available." No false promises, no silent failure, no dependency on third-party free tiers.

---

## Technical Design

### Knowledge base (the actual answer engine)

**Source of truth:** `knowledge/` directory in the crabcakes repo. Currently 7 files, 412 lines, ~13KB. Will grow to ~3,000-4,000 lines across ~10 files for v1.

**New files needed (Tier 1 content):**
- `install.md` — install verification per platform, common install errors with fixes
- `providers.md` — provider configuration for OpenRouter, Ollama, OpenAI, Anthropic, Google
- `gateway-setup.md` — gateway connection walkthrough, common failures

**Existing files to expand (Tier 2 content):**
- `setup.md` — currently 51 lines → target ~300 lines
- `configuration.md` — currently 59 lines → target ~400 lines
- `agents.md` — currently 70 lines → target ~400 lines
- `features.md` — currently 56 lines → target ~350 lines
- `commands.md` — currently 51 lines → target ~250 lines
- `gateway.md` — currently 47 lines → target ~200 lines
- `troubleshooting.md` — currently 78 lines → target ~500 lines

**Phase 2 file (Tier 3 content):**
- `workflows.md` — workflow patterns, customization, multi-agent strategies. New file, target ~500 lines.

**Tier 4 content (v2, not in v1 deliverable):**
- `updates.md` — version-update walkthroughs, release-notes-driven guidance (target ~250 lines)
- `bug-reports.md` — guided bug-report composition, log capture, repro templates (target ~200 lines)
- `uninstall.md` — clean removal of CrabCakes + config + cache (target ~150 lines)
- Expansion of `troubleshooting.md` for deeper, edge-case content beyond what Tier 2 needs (target ~500 lines added)

Tier 4 KB files can be added incrementally after v1 ships, just by writing the `.md` and re-running the indexer. No re-architecture required. **Total v1 deliverable: ~3,000-4,000 lines across ~10 files.** Total with Tier 4: ~4,500-5,500 lines across ~13 files.

### Indexing pipeline

**Model:** `BAAI/bge-small-en-v1.5` (130MB, MIT-licensed, runs on CPU, top-tier open embedding model for English retrieval). Falls back to `sentence-transformers/all-MiniLM-L6-v2` (80MB) if the larger model is unavailable.

**Storage:**
- `knowledge/.index/chunks.json` — list of `{id, source, text, section}` records
- `knowledge/.index/embeddings.npy` — `np.float32` array, shape `(N, 384)`
- Both rebuilt offline by `scripts/rebuild_kb_index.py`
- Both committed to the repo so users get the pre-built index on install

**Build cost:** ~5 seconds for 100 chunks. One-time, offline, batch.

**Query cost:** ~50ms per question (model warm), ~2s first question after app launch (cold start, model load). All local. No network.

### Lookup module

**Interface:** `kb_lookup(question: str, top_k: int = 3) -> list[KBChunk]`

**Behavior:**
1. Load `embeddings.npy` and `chunks.json` on first call (cached)
2. Embed the question with the same model that built the index
3. Compute cosine similarity between question vector and all chunk vectors
4. Return top-K chunks above a confidence threshold (default 0.3); empty list if no chunk is above threshold
5. Caller decides what to do with empty list (Tier 1 returns static wizard, Tier 2 says "I don't have info on that," Tier 3 escalates to LLM)

**Wiring:**
- `agent/kb_lookup.py` — new module, ~120 lines
- `agent/auxilium_runtime.py` (or augment existing `agent_runtime_handler.py`) — calls `kb_lookup` before LLM in Auxilium's runtime path
- The LLM system prompt is augmented: "For factual questions about CrabCakes, call `kb_lookup` first. If chunks are returned, ground your answer in them. If empty list, say you don't know."

### First-run wizard (Tier 1)

**No LLM call required.** A static welcome message displayed when Auxilium is in Phase 1 mode (no provider configured):

> "Hi, I'm Auxilium 🦀 — your assistant for CrabCakes. Before I can answer questions, I need a 'brain' to think with. Pick one:
>
> **(a) OpenRouter free** — online, no key, OK quality
> **(b) Ollama local** — install with `curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2:7b`, runs offline
> **(c) Bring your own key** — OpenAI, Anthropic, Google, etc.
>
> Reply with the letter or click a button."

The three options write different things to `~/.config/crabcakes/agents/auxilium.yaml`:
- **(a) OpenRouter** — set `provider: openrouter`, `model: openrouter/free`
- **(b) Ollama** — set `provider: ollama`, `model: llama3.2:7b`, `endpoint: http://localhost:11434`
- **(c) BYOK** — prompt for provider, model, API key; write fields

After the user picks, Auxilium verifies the provider is reachable. If yes, Auxilium switches to Phase 2 (KB + LLM synthesis). If no, Auxilium stays in Phase 1 and offers troubleshooting steps from `knowledge/troubleshooting.md` (which is *also* indexed and retrievable).

### Brain upgrade moment

When the user configures a provider, the `load_agent_config()` path detects it and switches Auxilium's runtime mode from Phase 1 to Phase 2. The LLM system prompt is augmented with the synthesis instruction. The KB lookup path is unchanged. The user notices nothing except "answers feel more conversational now."

---

## Phasing

### Phase 1 — Tier 1 (shippable in ~1 week)

**Goal:** Auxilium works on a fresh install with zero configuration. KB-first, no LLM required for Tier 1.

**Deliverables:**
1. `scripts/rebuild_kb_index.py` — one-file indexer (~80 lines)
2. `agent/kb_lookup.py` — lookup module (~120 lines)
3. `knowledge/.index/chunks.json` and `knowledge/.index/embeddings.npy` — pre-built and committed
4. New KB file `knowledge/install.md` (Tier 1.1: install verification)
5. New KB file `knowledge/providers.md` (Tier 1.3: provider configuration)
6. Auxilium system prompt update: call `kb_lookup` for factual questions
7. First-run wizard UI: static 3-button picker, no LLM call
8. Verification: `xvfb-run` smoke test, `pytest` for `kb_lookup` module

**Exit criteria:** A fresh-install user can open Auxilium, get the static welcome, pick a provider, and verify the provider works. All of this works without an LLM.

### Phase 2 — Tier 2 (shippable in ~2-3 weeks after Phase 1)

**Goal:** Auxilium answers factual "how do I…" questions with KB-synthesized answers.

**Deliverables:**
1. Expand existing 7 KB files to 2-3× their current size (~1,200-1,500 added lines)
2. `agent/auxilium_synthesis.py` — LLM synthesis layer (~80 lines)
3. `compose_system_prompt()` augmentation: when provider is configured, add synthesis instruction
4. Tier 2 verification: 20-30 sample "how do I…" questions, manual review of answers

**Exit criteria:** A user with a configured provider asks "how do I configure the gateway URL?" and gets a friendly, synthesized answer grounded in `knowledge/configuration.md`.

### Phase 3 — Tier 3 (shippable in ~3-4 weeks after Phase 2)

**Goal:** Auxilium answers power-user questions beyond the KB.

**Deliverables:**
1. New KB file `knowledge/workflows.md` (Tier 3 content, ~500 lines)
2. LLM is unconstrained for Tier 3 questions (no longer "ground in KB chunks")
3. Tier 3 verification: 10-15 sample power-user questions, manual review

**Exit criteria:** A user with a configured provider asks "when should I use Coder vs. Debugger?" and gets a thoughtful comparison drawn from `knowledge/agents.md` and the LLM's general reasoning.

---

## Risks

### R1 — KB quality
The KB is the answer engine. Bad KB = bad answers. Mitigation: Phase 1 only ships *after* `install.md` and `providers.md` are written to a quality bar (estimate: 200+ lines each, real commands, real error messages, real fixes). Phase 2 expansion is gated on a peer review of the rewritten files.

### R2 — Embedding model availability
`BAAI/bge-small-en-v1.5` is 130MB and downloads on first use. On a flaky network or behind a firewall, the download fails. Mitigation: ship the model in the app bundle (a one-time 130MB hit on the installer), or fall back to the smaller 80MB `all-MiniLM-L6-v2`. Pick the model at runtime based on what's available.

### R3 — KB lookup latency on first question
Model cold start is ~2s. Mitigation: load the model lazily on first Auxilium interaction, not at app launch. The user will see a small spinner the first time they ask a question, then it's instant.

### R4 — LLM hallucination despite KB grounding
A configured LLM can still hallucinate commands or flags that don't exist. Mitigation: the system prompt explicitly says "ground your answer in the KB chunks; if a specific command isn't in the chunks, say 'I don't have a verified command for that — check the docs at <link>'". This is a soft constraint, not a hard one. Phase 3 may add a "cite your sources" mechanism where the LLM is required to quote from the chunks.

### R5 — Ollama detection on Windows
`ollama` is a single binary, but Windows detection requires `where ollama` instead of `which ollama`. Mitigation: cross-platform detection in `agent/auxilium_runtime.py`; on Windows, also check `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`.

---

## Out of scope (v1)

- **Tier 4 help topics (v2):** updates walkthroughs (`updates.md`), bug-report composition (`bug-reports.md`), uninstall (`uninstall.md`), deep troubleshooting expansion. The KB architecture supports adding these after v1 ships; they're not in the v1 deliverable list. See the "Tier 4 content" subsection above for the specific files and line-count targets.
- Multi-language KB (English only for v1)
- KB authoring tools (writers edit `.md` files directly and re-run the indexer)
- KB versioning / changelog
- User-supplied custom KBs (the "can I make my own knowledge base for my team?" question is Phase 3)
- LLM-side citation / source linking
- Voice / audio answers
- Telemetry on which KB chunks get retrieved (useful for KB iteration, but a privacy concern to resolve first)

---

## Acceptance criteria (umbrella)

For the proposal to be considered done:
- **AC-P1:** All three SPECs (`SPEC-auxilium-tier-1.md`, `SPEC-auxilium-tier-2.md`, `SPEC-auxilium-tier-3.md`) exist, are reviewed, and have their phase deliverables marked DONE in `PROPOSAL_PRIORITY_ROADMAP_2026-06-12.md`.
- **AC-P2:** A fresh-install user with empty `~/.config/crabcakes/` can open Auxilium and (a) run the first-run wizard, (b) configure any of the three provider options, (c) verify the provider works — all without consulting external documentation.
- **AC-P3:** Auxilium correctly answers ≥80% of "how do I…" questions in the Tier 2 acceptance test (a 20-30 question manual review) using only the KB.
- **AC-P4:** A user with a configured provider can have a multi-turn conversation with Auxilium about Tier 3 topics and get answers that are "useful, even if not always perfect" per the Phase 3 review.

---

## What's next

This proposal is the umbrella. The first spec to write is `SPEC-auxilium-tier-1.md` (first-run setup), per the Captain's instruction in conversation 2026-06-13 ("the first spec covering number 1"). The Tier 2 and Tier 3 specs come after Phase 1 ships, with content shaped by what we learn from Phase 1's user testing.

**Captain decision points:**
1. Approve the three-tier scope and the KB-first / LLM-second phasing?
2. Approve `BAAI/bge-small-en-v1.5` as the embedding model, or prefer a different one?
3. Approve the Phase 1 deliverable list (the 8 items above) as the ship target?
4. Approve writing `SPEC-auxilium-tier-1.md` as the next deliverable?
