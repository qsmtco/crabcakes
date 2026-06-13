# SPEC: Auxilium Tier 1 — First-Run Setup

**Date:** 2026-06-13
**Author:** Qaster
**Parent proposal:** `docs/proposals/PROPOSAL-auxilium-three-tier-help-agent.md`
**Status:** Draft — pending Captain approval
**Phase:** 1 of 3 (shippable in ~1 week)
**Effort:** ~5-7 days

---

## Goal

A fresh-install user with an empty `~/.config/crabcakes/` can open Auxilium and complete the entire first-run setup — install verification, gateway connection, provider configuration, smoke test — **without an LLM configured and without leaving the app.**

This is the "out of the box" promise the original Crabcakes help-agent PROPOSAL made in 2026-05-30 and never kept. This spec keeps it.

---

## Scope (in)

- **KB indexing pipeline** (indexer + lookup module)
- **2 new KB files** for Tier 1 content: `knowledge/install.md`, `knowledge/providers.md`
- **Auxilium system prompt update** to call `kb_lookup` for factual questions
- **First-run wizard UI** with static 3-button provider picker (no LLM call)
- **Smoke test** that exercises the wizard end-to-end

## Scope (out)

- Tier 2 content (KB file expansion for features/configuration/agents/etc.) — separate SPEC, Phase 2
- Tier 3 content (`workflows.md`) — separate SPEC, Phase 3
- LLM synthesis layer (Phase 2) — `kb_lookup` returns raw chunks; no LLM rephrasing in this phase
- Multi-language KB
- Custom user KBs
- Telemetry

---

## Tier 1 surface area

The user-facing surface for Tier 1 is a *first-run wizard* that replaces the current empty/errored Auxilium greeting. The wizard runs entirely on KB chunks + a static welcome message; **no LLM is invoked during Tier 1.**

### Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. App launches                                                │
│ 2. Auxilium tab auto-opens (existing behavior, unchanged)      │
│ 3. Auxilium checks: provider configured?                       │
│    ├─ YES  → show "Hi, I'm Auxilium" (synthesized greeting)    │
│    └─ NO   → show Tier 1 wizard (this SPEC's deliverable)      │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 1: install check                                    │
│   • Detect platform, Python, GTK4, PyGObject                   │
│   • Report OK / missing with remediation                       │
│   • "Continue" button → step 2                                 │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 2: gateway check                                   │
│   • Try WebSocket connect to configured gateway URL            │
│   • OK / failed with remediation                               │
│   • "Continue" → step 3                                        │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 3: provider picker (static, no LLM)                 │
│   • (a) OpenRouter free — no key, online                       │
│   • (b) Ollama local — install hint, offline                   │
│   • (c) Bring your own key — provider + key form               │
│   • Writes ~/.config/crabcakes/agents/auxilium.yaml            │
│   • Verifies provider reachable                                │
│   • On success: Auxilium is now Phase 2 capable                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Deliverables

### D1. `scripts/rebuild_kb_index.py` — KB indexer

**Purpose:** Read all `knowledge/*.md` files, chunk them, embed with `BAAI/bge-small-en-v1.5`, save the index to disk.

**Interface:**
```bash
python3 scripts/rebuild_kb_index.py [--model BAAI/bge-small-en-v1.5] [--out knowledge/.index/]
```

**Behavior:**
- Glob `knowledge/*.md` (excluding `knowledge/.index/`)
- Split each file into chunks by `##` headers (each `## Section` is one chunk; pre-amble is one chunk)
- Embed all chunks with the configured Sentence-Transformers model
- Save `chunks.json` (list of `{id, source, section, text}`) and `embeddings.npy` (float32, shape `(N, 384)`)
- Print summary: "Indexed N chunks from M files"

**Chunking rule:** Split on `##` (level-2) headings. Each chunk ≤2000 chars; if a section is longer, split on `###` (level-3) or paragraph boundaries. This keeps chunks topical and roughly uniform in size.

**Idempotency:** Re-running on unchanged KB produces a byte-identical `embeddings.npy` (deterministic model + same inputs).

**Lines:** ~80.

### D2. `agent/kb_lookup.py` — lookup module

**Purpose:** Given a question, return the top-K most relevant KB chunks.

**Public API:**
```python
@dataclass
class KBChunk:
    id: str
    source: str      # e.g. "knowledge/install.md"
    section: str     # e.g. "Verifying GTK4 on Linux"
    text: str
    score: float     # cosine similarity, 0..1

def kb_lookup(question: str, top_k: int = 3, min_score: float = 0.3) -> list[KBChunk]:
    """Embed the question, return top-K chunks above min_score, sorted desc by score."""
```

**Behavior:**
- Lazy-load the model and index on first call (singleton pattern, ~200MB RAM after first load)
- Cache the model in module-level `_state` dict; subsequent calls reuse it
- Cosine similarity via `numpy.dot` on L2-normalized vectors
- Returns `[]` if no chunk is above `min_score` (the caller's signal to say "I don't have info on that")
- Logs query, top-3 chunk IDs, and timing at DEBUG level

**Test coverage:**
- `test_kb_lookup.py` — 8 tests:
  1. Returns empty list for empty/no-index state
  2. Returns top-K chunks sorted by score
  3. Filters chunks below `min_score`
  4. Caches the model across calls (no re-load)
  5. Returns correct chunk metadata
  6. Handles question with no relevant match → empty list
  7. Handles multi-word questions
  8. Question + chunk embedding use the same model (sanity test)

**Lines:** ~120.

### D3. `knowledge/install.md` — Tier 1.1 content

**Purpose:** Help a fresh-install user verify their environment and fix common install errors.

**Target:** 200-300 lines.

**Sections:**
- Platform detection (Linux/macOS/Windows)
- Python version requirement (3.11+)
- GTK4 + PyGObject verification per platform
  - Debian/Ubuntu: `apt install ...`
  - Fedora: `dnf install ...`
  - Arch: `pacman -S ...`
  - macOS (Homebrew): `brew install ...`
  - Windows: official GTK4 runtime installer
- Common errors and fixes (table):
  - `ModuleNotFoundError: No module named 'gi'`
  - `Gtk-CRITICAL **: cannot open display` (Linux X11/Wayland)
  - `externally-managed-environment` (PEP 668)
  - `ImportError: libgtk-4.so.1: cannot open shared object file`
  - PyGObject introspection cache errors
- Verifying the install (`crabcakes --version` smoke command)
- When to ask for help (link to troubleshooting.md)

**Source format:** GitHub-flavored Markdown, level-2 headers per chunking rule.

### D4. `knowledge/providers.md` — Tier 1.3 content

**Purpose:** Walk a user through configuring any of the five supported LLM providers.

**Target:** 250-350 lines.

**Sections (one per provider):**
- **OpenRouter (free tier)** — sign-up, API key, model selection, env var, `auxilium.yaml` snippet
- **Ollama (local)** — install command, model pull, endpoint URL, `auxilium.yaml` snippet
- **OpenAI** — API key, model names, env var, `auxilium.yaml` snippet
- **Anthropic** — API key, model names, env var, `auxilium.yaml` snippet
- **Google (Gemini)** — API key, model names, env var, `auxilium.yaml` snippet

**Common sections:**
- Verifying the provider is reachable (`curl` / `ollama list` smoke checks)
- Storing API keys (`agent.json` vs env var vs system keyring)
- Switching providers mid-session
- Common errors per provider (401, 429, model-not-found, etc.)
- Cost expectations per provider (free tier / paid tier / local = free)

**`auxilium.yaml` snippets:** every provider section ends with a complete copy-pasteable yaml block that the user can drop into `~/.config/crabcakes/agents/auxilium.yaml`.

### D5. `knowledge/gateway-setup.md` — Tier 1.2 content (Phase 1.5? see Risks)

**Status:** Defer to a follow-up commit. Phase 1 ships with install.md + providers.md only. gateway-setup.md is added in a Phase 1.5 patch if the wizard's gateway step (D7) needs more KB content than what's already in `knowledge/gateway.md`. The existing `gateway.md` (47 lines) is enough for Phase 1's gateway-check step.

### D6. `prompts/system/auxilium.md` — system prompt update

**Change:** Add a section to the existing system prompt that tells the LLM to call `kb_lookup` for factual questions.

**Current behavior:** The system prompt says "Use `web_fetch` to read the relevant file from `https://raw.githubusercontent.com/qsmtco/crabcakes/main/knowledge/`."

**New behavior:** Two modes:

1. **Phase 1 (no provider configured, Tier 1 only):** The runtime short-circuits to the wizard. The system prompt is replaced with a static welcome that says "I'm Auxilium. Let's get you set up." and presents the wizard.

2. **Phase 2+ (provider configured):** The system prompt retains the existing web_fetch instruction as a fallback, but adds a new paragraph:

   > **Preferred lookup path:** For factual questions about CrabCakes setup, configuration, features, commands, agents, or troubleshooting, call `kb_lookup(question)` first. If it returns chunks, ground your answer in those chunks — quote them, link to them, or summarize them. If it returns an empty list (no confident match), fall back to `web_fetch` to read the live docs from GitHub, or say you don't know.

**Why this matters:** In Phase 1, the LLM isn't even invoked, so the system prompt change is only meaningful once the user has a provider. But the prompt needs to be ready *before* the wizard completes, because the wizard writes the new `auxilium.yaml` and the next message is the first LLM call.

### D7. First-run wizard UI

**Location:** `ui/views/auxilium_wizard.py` (new) + glue in `ui/handlers/auxilium_runtime.py` (new) or extension of `agent_runtime_handler.py`.

**Behavior:**
- Trigger: Auxilium tab opens, `load_agent_config()` returns no usable provider
- Renders a 3-step wizard in the Auxilium tab area, replacing the default chat input temporarily
- Step 1 (install check): Runs the verification commands from `knowledge/install.md` (section "Verifying the install"). Shows a checklist with green checks / red X's + remediation hints. "Continue" button (disabled until at least the critical checks pass).
- Step 2 (gateway check): Reads `~/.config/crabcakes/agent.json` for the gateway URL, attempts a WebSocket connect with 3s timeout. Shows OK / failed + remediation from `knowledge/gateway.md`. "Continue" button.
- Step 3 (provider picker): Three buttons:
  - **(a) OpenRouter free** — writes `provider: openrouter`, `model: openrouter/free`
  - **(b) Ollama local** — writes `provider: ollama`, `model: llama3.2:7b`, `endpoint: http://localhost:11434` (with a hint to install Ollama if not found)
  - **(c) Bring your own key** — form with provider dropdown, model field, API key field
  - On submit: writes the file, attempts a smoke-call (1-token completion or `ollama list`), shows OK / error
  - On OK: dismisses the wizard, switches the Auxilium tab to the normal chat view, displays a synthesized "Hi, I'm Auxilium 🦀 — your assistant for CrabCakes. What can I help you with?" message

**Wizard state:** Stored in a `AuxiliumWizardState` dataclass in the runtime module. Lost on app restart — the user resumes from wherever they were. (Resuming mid-wizard is a Phase 2 nicety.)

**No LLM calls in the wizard.** The wizard is a deterministic state machine driven by platform detection + WebSocket probes + filesystem writes.

**Lines:** ~250 (UI + state + verification commands).

### D8. `tests/test_auxilium_tier1.py` — end-to-end smoke

**Purpose:** Verify the full wizard flow works on a synthetic fresh-install state.

**Tests:**
1. `test_kb_indexer_produces_valid_index` — runs `rebuild_kb_index.py` against a fixture KB, asserts `embeddings.npy` shape and `chunks.json` schema
2. `test_kb_lookup_returns_relevant_chunks` — asks "how do I install on Ubuntu?" against the fixture index, asserts the top chunk is from `install.md` and the section is Linux/APT-related
3. `test_kb_lookup_handles_unrelated_question` — asks "what's the capital of France?" against the fixture, asserts empty list (no confident match)
4. `test_wizard_writes_auxilium_yaml_openrouter` — drives the wizard to step 3, picks (a), asserts the file is written with correct fields
5. `test_wizard_writes_auxilium_yaml_ollama` — same for (b)
6. `test_wizard_writes_auxilium_yaml_byok` — same for (c) with mocked key entry
7. `test_wizard_state_persists_across_steps` — drives the wizard through all 3 steps, asserts state transitions

**Lines:** ~150.

---

## Risks

### R1 — Embedding model download on first run

`BAAI/bge-small-en-v1.5` is 130MB. On a flaky network, the first-run download fails. Mitigation: ship the model in the app bundle (~130MB hit on the installer), or fall back to the 80MB `all-MiniLM-L6-v2`. The fallback is a one-line config change.

### R2 — `xvfb-run` + GTK test flakiness

The wizard UI uses GTK widgets. Existing tests have flakiness (see `test_connection_sync_handler.py` failure on pristine main). Mitigation: keep wizard tests headless-friendly; test the verification logic separately from the UI rendering. The 7 tests in D8 are mostly logic, not pixel-pushing.

### R3 — Wizard state lost on crash

If the user is mid-wizard and the app crashes, they restart from step 1. Mitigation: persist wizard state to `~/.config/crabcakes/auxilium_wizard_state.json` after each step completes. This is a 30-line addition, deferred to Phase 1.5 unless time permits.

### R4 — Existing `crabcakes.yaml` users

Users with the legacy `crabcakes.yaml` (now `auxilium.yaml` via the rename migration) won't see the wizard. The wizard only triggers on *no* provider. Mitigation: the rename migration writes a working OpenRouter provider, so the wizard is bypassed. Document this in the migration changelog.

### R5 — `gateway-setup.md` may be needed sooner than Phase 1.5

The existing `knowledge/gateway.md` (47 lines) is the only gateway content. The wizard's step 2 needs error messages and remediation hints. Mitigation: expand `gateway.md` in the same commit as D3-D4 if `gateway.md` is found insufficient during D7 implementation. No new file needed; the indexer picks up the expanded file automatically.

---

## Acceptance criteria

This SPEC is DONE when all of the following are true:

- **AC-T1-1:** `scripts/rebuild_kb_index.py` runs cleanly against the current 7 KB files, produces `embeddings.npy` (shape `(N, 384)`, dtype `float32`) and `chunks.json` (list of valid `{id, source, section, text}` dicts).
- **AC-T1-2:** `agent/kb_lookup.py` returns the correct top-3 chunks for 8-10 hand-picked "how do I install…" questions against the indexed 7 files + the 2 new files (install.md, providers.md). Verified by a hand-review table in `tests/test_kb_lookup.py` comments.
- **AC-T1-3:** `knowledge/install.md` exists, ≥200 lines, covers all platforms in the D3 section list, and has copy-pasteable remediation commands verified by manual run on Linux.
- **AC-T1-4:** `knowledge/providers.md` exists, ≥250 lines, covers all 5 providers in the D4 section list, and has working `auxilium.yaml` snippets for each.
- **AC-T1-5:** `prompts/system/auxilium.md` has the new "Preferred lookup path" paragraph.
- **AC-T1-6:** A fresh-install user (empty `~/.config/crabcakes/`) can launch the app, see the Auxilium wizard, complete all 3 steps, and end up with a working Auxilium that answers a factual question. Verified by `xvfb-run` smoke + manual test.
- **AC-T1-7:** An existing user with `auxilium.yaml` already configured (from the rename migration) does *not* see the wizard. Verified by `xvfb-run` smoke.
- **AC-T1-8:** All 7 tests in `tests/test_auxilium_tier1.py` pass.
- **AC-T1-9:** Existing 593 tests still pass. (Pre-existing failure in `test_connection_sync_handler.py` is excluded as flaky/unrelated.)
- **AC-T1-10:** `G_DEBUG=fatal-criticals` smoke launch is clean.

---

## Out of scope (deferred to Phase 2+)

- LLM synthesis layer on top of KB chunks (Phase 2)
- Tier 2 KB file expansion (Phase 2)
- Tier 3 KB file (`workflows.md`, Phase 3)
- Multi-language KB
- KB authoring tools
- Custom user KBs
- LLM-side citation / source linking
- Voice / audio answers
- Telemetry

---

## Phasing within this SPEC

This SPEC can ship in a single PR, but the implementation order matters:

1. **D1 + D2** — indexer + lookup module. ~150 lines. Ship as a PR with tests, against the existing 7 KB files. This is the riskiest unknown — verify the architecture works before writing content.
2. **D3 + D4** — install.md + providers.md. ~500 lines of writing. The first 100 lines are the most important; the remaining 400 can be incremental.
3. **D5** — expand `knowledge/gateway.md` if needed (deferred until D7 needs it).
4. **D6** — system prompt update. 1 paragraph.
5. **D7** — wizard UI. ~250 lines.
6. **D8** — tests. ~150 lines.

The two risk-bearing pieces (D1/D2 architecture, D7 wizard UX) are split into separate PRs to keep review surface small.

---

## What's next

When this SPEC is approved and Phase 1 ships, the next deliverable is `SPEC-auxilium-tier-2.md` (the help-assistant tier). Tier 2 SPEC content will be shaped by what we learn from Phase 1's real-user testing — particularly which Tier 2 questions the KB lookup actually answers well and which it doesn't.

**Captain decision points:**
1. Approve the 10 acceptance criteria as the DONE bar?
2. Approve splitting D1/D2 from D7 into separate PRs?
3. Approve writing `install.md` and `providers.md` in this PR (vs. splitting KB writing from code work)?
4. Approve `gateway-setup.md` being deferred to Phase 1.5 (vs. included in Phase 1)?
