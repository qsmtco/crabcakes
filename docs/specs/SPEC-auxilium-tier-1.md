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
- **Auxilium system prompt update** to use `kb_lookup` for factual questions
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

## Architecture constraints (from ARCHITECTURE.md)

Every deliverable must obey ARCHITECTURE.md. Key rules that apply:

| Rule | Source | Implication for this SPEC |
|---|---|---|
| `agent/` = no UI dependencies | §2 Directory Structure | `kb_lookup.py` in `agent/` — pure Python, no GTK, no network at import time |
| `ui/views/` = view widgets only | §2, §8.2 | Wizard view in `ui/views/`, logic in `ui/handlers/` |
| Callbacks are the communication mechanism | §5 Callback Pattern | Wizard communicates via callbacks, never imports sibling UI components |
| New modules → update ARCHITECTURE.md in same commit | §0 | All new files documented in §3 and §13 of ARCHITECTURE.md |
| No imports from `ui/` in `agent/` | §2 (Critical rule) | `agent/kb_lookup.py` must not import any `ui/` module |
| Tests in `tests/` | §8.5 | One file per module: `test_kb_lookup.py`, `test_auxilium_tier1.py` |
| `snake_case.py` for all Python files | §6 Naming Conventions | `rebuild_kb_index.py`, `kb_lookup.py`, `auxilium_wizard.py` |

---

## Tier 1 surface area

The user-facing surface for Tier 1 is a *first-run wizard* that replaces the current empty/errored Auxilium greeting. The wizard runs entirely on KB chunks + a static welcome message; **no LLM is invoked during Tier 1.**

### Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. App launches                                                │
│ 2. Auxilium tab auto-opens (existing behavior, unchanged)      │
│ 3. Auxilium checks: provider configured?                       │
│    ├─ YES  → normal chat (Phase 2 — out of scope for this SPEC)│
│    └─ NO   → show Tier 1 wizard (this SPEC's deliverable)      │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 1: install check                                    │
│   • Detect platform, Python, GTK4, PyGObject                   │
│   • Report OK / missing with remediation                       │
│   • "Continue" button → step 2                                 │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 2: gateway check                                   │
│   • Read gateway URL from ~/.config/crabcakes/agent.json       │
│   • Try WebSocket connect (3s timeout)                          │
│   • OK / failed with remediation                               │
│   • "Continue" → step 3                                        │
├─────────────────────────────────────────────────────────────────┤
│ Wizard step 3: provider picker (static, no LLM)               │
│   • (a) OpenRouter free — no key, online                        │
│   • (b) Ollama local — install hint, offline                   │
│   • (c) Bring your own key — provider + key form               │
│   • Writes ~/.config/crabcakes/agents/auxilium.yaml            │
│   • Verifies provider reachable                                │
│   • On success: dismiss wizard, switch Auxilium to normal chat  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Deliverables

### D1. `scripts/rebuild_kb_index.py` — KB indexer

**Location:** `scripts/rebuild_kb_index.py` (ARCHITECTURE.md §13 confirms `scripts/` exists)

**Purpose:** Read all `knowledge/*.md` files, chunk them, embed with `BAAI/bge-small-en-v1.5`, save the index to disk.

**Interface:**
```bash
python3 scripts/rebuild_kb_index.py [--model BAAI/bge-small-en-v1.5] [--out knowledge/.index/]
```

**Behavior:**
- Glob `knowledge/*.md` (excluding `knowledge/.index/`)
- Split each file into chunks by `##` (level-2) headers. Each chunk ≤2000 chars; longer sections split on `###` or paragraph boundaries.
- Embed all chunks with the configured Sentence-Transformers model
- Save `chunks.json` (`{id, source, section, text}`) and `embeddings.npy` (float32, shape `(N, 384)`)
- Print: "Indexed N chunks from M files"

**Chunking rule:** Split on `##` headings. Keeps chunks topical and uniform. Chunks >2000 chars split further.

**Idempotency:** Re-running on unchanged KB produces byte-identical `embeddings.npy`.

**ARCHITECTURE.md note:** This is a standalone build script, not a module. It is not imported by any runtime code. It is run offline (by the developer or in CI) to rebuild the index when KB content changes.

**Lines:** ~80.

---

### D2. `agent/kb_lookup.py` — lookup module

**Location:** `agent/kb_lookup.py` (ARCHITECTURE.md §2: `agent/` = local agent runtime, no UI dependencies)

**Purpose:** Given a question, return the top-K most relevant KB chunks using cosine similarity on embeddings.

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
- Lazy-load the model and index on first call (singleton in module-level `_state` dict)
- Cache the model; subsequent calls reuse it without re-loading
- Cosine similarity via `numpy.dot` on L2-normalized vectors
- Returns `[]` if no chunk is above `min_score` — caller uses this as "no confident match"
- DEBUG-level log: query, top-3 chunk IDs, timing

**`kb_lookup` integration into the agent runtime** (Phase 2 wiring, not in this SPEC's scope but documented here for consistency):

There are two integration paths. Phase 1 ships only the lookup module. Phase 2 chooses one:

- **Option A (preprocessing):** In `AgentRuntime.send_message()`, before building the API message list, check if `agent_role == "helper"` and `kb_lookup` index exists. If so, run `kb_lookup(question)` and prepend a synthetic user message: `"Context from knowledge base: [chunks]. User question: {question}"`. The LLM sees the KB context naturally. No tool definition needed.
- **Option B (tool):** Add `kb_lookup` as a tool in `agent/tools.py` with `name="kb_lookup"`, `parameters={"type": "object", "properties": {"question": {"type": "string"}}}`. The LLM calls it when it needs KB context. Requires `requires_approval=False`.

**Decision for Phase 2:** Deferred until D2 is implemented and the preprocessing path is tested. Option A is recommended (simpler, no tool-schema change, works with all providers).

**ARCHITECTURE.md constraints:**
- No imports from `ui/`, `gateway/`, or `subprocess`
- No GTK at import time
- `sentence_transformers` and `numpy` are pure Python — allowed in `agent/`

**Test coverage** (`tests/test_kb_lookup.py`, 8 tests):
1. Returns empty list when index is missing
2. Returns top-K chunks sorted by score descending
3. Filters chunks below `min_score`
4. Model is cached across calls (no re-load)
5. Returns correct chunk metadata (`id`, `source`, `section`, `text`, `score`)
6. Unrelated question → empty list
7. Multi-word question handled correctly
8. Question and chunk embeddings use the same model (sanity)

**Lines:** ~120.

---

### D3. `knowledge/install.md` — Tier 1.1 content

**Location:** `knowledge/install.md` (existing `knowledge/` directory, ARCHITECTURE.md §2)

**Purpose:** Help a fresh-install user verify their environment and fix common install errors.

**Target:** 200-300 lines.

**Sections (each `##` = one chunk for indexing):**
- Platform detection (Linux/macOS/Windows)
- Python version requirement (3.11+)
- GTK4 + PyGObject verification per platform:
  - Debian/Ubuntu: `apt install libgirepository1.0-dev libgtk-4-dev ...`
  - Fedora: `dnf install python3-gobject gtk4 ...`
  - Arch: `pacman -S python-gobject gtk4 ...`
  - macOS (Homebrew): `brew install pygobject4 gtk4 ...`
  - Windows: official GTK4 runtime installer link
- Common errors and fixes (table format):
  - `ModuleNotFoundError: No module named 'gi'` → install PyGObject
  - `Gtk-CRITICAL **: cannot open display` → set DISPLAY / check Wayland
  - `externally-managed-environment` (PEP 668) → use venv or `--break-system-packages`
  - `ImportError: libgtk-4.so.1: cannot open shared object file` → install GTK4 runtime
  - PyGObject introspection cache errors
- Verifying the install (`crabcakes --version` smoke command)
- When to ask for help (link to troubleshooting.md)

**Format:** GitHub-flavored Markdown. Level-2 `##` headers for chunking. Copy-pasteable commands.

---

### D4. `knowledge/providers.md` — Tier 1.3 content

**Location:** `knowledge/providers.md` (existing `knowledge/` directory)

**Purpose:** Walk a user through configuring any of the five supported LLM providers.

**Target:** 250-350 lines.

**Sections (one `##` per provider):**
- **OpenRouter (free tier)** — sign-up URL, API key retrieval, model selection, env var, `auxilium.yaml` snippet
- **Ollama (local)** — install command, model pull (`ollama pull llama3.2:7b`), endpoint URL, `auxilium.yaml` snippet
- **OpenAI** — API key, model names, env var, `auxilium.yaml` snippet
- **Anthropic** — API key, model names, env var, `auxilium.yaml` snippet
- **Google (Gemini)** — API key, model names, env var, `auxilium.yaml` snippet

**Common sections:**
- Verifying provider is reachable (curl / `ollama list` smoke checks)
- Storing API keys (env var vs `agent.json` vs system keyring)
- Switching providers mid-session
- Common errors per provider (401, 429, model-not-found, etc.)
- Cost expectations

**`auxilium.yaml` snippets:** Every provider section ends with a complete copy-pasteable yaml block.

---

### D5. `knowledge/gateway-setup.md` — deferred to Phase 1.5

**Status:** Not in this SPEC. The existing `knowledge/gateway.md` (47 lines) is sufficient for the wizard's step 2 gateway check. If during D7 implementation the existing content is insufficient, `gateway.md` is expanded in a Phase 1.5 patch — no new file needed.

---

### D6. `prompts/system/auxilium.md` — system prompt update

**Change:** Add a section to the existing system prompt for Phase 2 (provider configured).

**New paragraph for Phase 2 mode:**
> **Knowledge base lookup:** For factual questions about CrabCakes setup, configuration, features, commands, agents, or troubleshooting, the KB lookup runs automatically before my response is generated. If relevant chunks are returned, I ground my answer in them — quoting, linking, or summarizing the relevant section. If no confident match is found, I say I don't know and suggest the user configure a provider for richer answers.

**Phase 1 mode (no provider):** The runtime short-circuits to the wizard before the LLM is ever invoked. The system prompt change only takes effect after the wizard completes and a provider is configured.

**Lines changed:** ~5.

---

### D7. `ui/handlers/auxilium_wizard_handler.py` + `ui/views/auxilium_wizard.py`

**Architecture:** Two files per ARCHITECTURE.md §8.2 (Adding a New UI Component):
- `ui/handlers/auxilium_wizard_handler.py` — business logic, state machine, verification commands (no GTK imports)
- `ui/views/auxilium_wizard.py` — GTK4 view widget (no business logic; receives data from handler via callbacks)

**`ui/handlers/auxilium_wizard_handler.py` — public API:**
```python
class AuxiliumWizardHandler:
    def __init__(on_complete: Callable, on_error: Callable)
    def start() -> None                    # begin wizard, step 1
    def advance_to_gateway() -> None       # step 1 done → step 2
    def advance_to_provider() -> None       # step 2 done → step 3
    def set_provider_choice(choice: str, provider: str, model: str, api_key: str | None) -> None
    def get_state() -> WizardState          # returns current step + verification results
```

**State machine:**
```
IDLE → INSTALL_CHECK → GATEWAY_CHECK → PROVIDER_PICK → WRITING_CONFIG → DONE
```

**`ui/views/auxilium_wizard.py` — callback interface** (ARCHITECTURE.md §5):
```python
class AuxiliumWizard(Gtk.Box):
    def __init__(
        on_install_check_complete: Callable,
        on_gateway_check_complete: Callable,
        on_provider_selected: Callable,
    )
```

**View responsibilities:**
- Render the 3-step form (step indicators, content area, button bar)
- Call the provided callbacks when the user advances a step
- Never import any other UI component
- Never call `agent_runtime_handler` or any business logic directly

**Handler responsibilities:**
- Run install verification commands (platform detection, Python version, GTK4 check)
- Run gateway WebSocket probe (3s timeout)
- Write `auxilium.yaml` on provider selection
- Verify provider reachable after write
- Call `on_complete(provider_config)` on success; `on_error(message)` on failure

**Wizard wiring in `ui/window.py`:**
- In `MainWindow.__init__()`, after `AuxiliumRuntimeHandler` is created, check if Auxilium has a provider configured
- If no provider: create `AuxiliumWizard` and replace the Auxilium chat box content with the wizard widget
- On `on_complete`: dismiss wizard, restore normal Auxilium chat box, reload `auxilium.yaml`, switch Auxilium to Phase 2 mode

**No LLM calls in the wizard.** The wizard is a deterministic state machine. All verification is filesystem + network probe, not chat completion.

**Lines:** handler ~150, view ~150.

---

### D8. `tests/test_auxilium_tier1.py` — end-to-end smoke

**Location:** `tests/test_auxilium_tier1.py` (ARCHITECTURE.md §8.5: one file per module)

**Tests (7 tests):**
1. `test_kb_indexer_produces_valid_index` — runs indexer against fixture KB, asserts `embeddings.npy` shape `(N, 384)` float32 and `chunks.json` schema
2. `test_kb_lookup_returns_relevant_chunks` — asks "how do I install on Ubuntu?" against fixture index, asserts top chunk from `install.md` and Linux/APT section
3. `test_kb_lookup_handles_unrelated_question` — asks "what's the capital of France?" → empty list
4. `test_wizard_install_check_detects_platform` — runs install check, asserts platform is detected
5. `test_wizard_gateway_check_fails_gracefully` — with invalid URL, asserts error message
6. `test_wizard_writes_auxilium_yaml_openrouter` — drives provider selection, asserts file written with correct fields
7. `test_wizard_state_persists_across_steps` — advances through all 3 steps, asserts correct state transitions

**Lines:** ~150.

---

## Acceptance criteria

This SPEC is DONE when all of the following are true:

- **AC-T1-1:** `python3 scripts/rebuild_kb_index.py` runs cleanly against the current 7 KB files, produces `knowledge/.index/embeddings.npy` (shape `(N, 384)`, dtype `float32`) and `knowledge/.index/chunks.json` (list of valid `{id, source, section, text}` dicts).
- **AC-T1-2:** `agent/kb_lookup.kb_lookup()` returns the correct top-3 chunks for 8-10 hand-picked "how do I install…" questions against the indexed 7 files + the 2 new files. Verified by a hand-review table in `tests/test_kb_lookup.py` comments.
- **AC-T1-3:** `knowledge/install.md` exists, ≥200 lines, covers all platforms in the D3 section list, and has copy-pasteable remediation commands.
- **AC-T1-4:** `knowledge/providers.md` exists, ≥250 lines, covers all 5 providers in the D4 section list, and has working `auxilium.yaml` snippets for each.
- **AC-T1-5:** `prompts/system/auxilium.md` has the new "Knowledge base lookup" paragraph for Phase 2 mode.
- **AC-T1-6:** A fresh-install user (empty `~/.config/crabcakes/`) can launch the app, see the Auxilium wizard, complete all 3 steps, and end up with a working Auxilium that answers a factual question. Verified by `xvfb-run` smoke + manual test.
- **AC-T1-7:** An existing user with `auxilium.yaml` already configured does *not* see the wizard. Verified by `xvfb-run` smoke.
- **AC-T1-8:** All 7 tests in `tests/test_auxilium_tier1.py` pass.
- **AC-T1-9:** Existing 593 tests still pass. (Pre-existing failure in `test_connection_sync_handler.py` is excluded as flaky/unrelated.)
- **AC-T1-10:** `G_DEBUG=fatal-criticals` smoke launch is clean.

---

## Risks

### R1 — Embedding model download on first run
`BAAI/bge-small-en-v1.5` is 130MB. On a flaky network, first-run download fails. Mitigation: ship the model in the app bundle; fall back to `all-MiniLM-L6-v2` (80MB) if the larger model is unavailable. One-line config change.

### R2 — `xvfb-run` + GTK test flakiness
Existing tests have flakiness (pre-existing `test_connection_sync_handler.py` failure). Mitigation: test the verification logic separately from the UI rendering. D8 tests are mostly logic, not pixel-pushing.

### R3 — Wizard state lost on crash
Mid-wizard crash → user restarts from step 1. Mitigation: persist wizard state to `~/.config/crabcakes/auxilium_wizard_state.json` after each step. 30-line addition, deferred to Phase 1.5.

### R4 — `kb_lookup` in `agent/` on a machine without sentence-transformers
If `sentence_transformers` import fails, `kb_lookup` should degrade gracefully: return `[]` and log a warning. The agent still works (KB lookup fails silently, LLM answers without KB grounding). No crash.

### R5 — Ollama detection on Windows
`ollama` check uses `which` on Unix. On Windows, also check `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`. Implemented in `auxilium_wizard_handler.py`.

---

## ARCHITECTURE.md updates required (in the same commit as the code)

Per ARCHITECTURE.md §0, this SPEC's code commit must include corresponding ARCHITECTURE.md updates:

| File added/changed | ARCHITECTURE.md section to update |
|---|---|
| `agent/kb_lookup.py` | §3: add `agent/kb_lookup.py` — KB lookup module; §13: add to file inventory |
| `ui/handlers/auxilium_wizard_handler.py` | §3: add `auxilium_wizard_handler.py`; §13: add to file inventory |
| `ui/views/auxilium_wizard.py` | §3: add `auxilium_wizard.py`; §13: add to file inventory |
| `scripts/rebuild_kb_index.py` | §13: add to file inventory (scripts/ already documented) |
| `knowledge/install.md`, `knowledge/providers.md` | §2: note expansion of `knowledge/` directory |
| `knowledge/.index/` (generated) | `.gitignore` entry: `knowledge/.index/` |

---

## Out of scope (deferred to Phase 2+)

- LLM synthesis layer on top of KB chunks (Phase 2)
- Tier 2 KB file expansion (Phase 2)
- Tier 3 KB file (`workflows.md`, Phase 3)
- Wizard state persistence across crashes (Phase 1.5)
- `gateway-setup.md` (Phase 1.5)
- Multi-language KB
- KB authoring tools
- Custom user KBs
- LLM-side citation / source linking
- Voice / audio answers
- Telemetry

---

## Phasing within this SPEC

Implementation order (architectural risk first):

1. **D2** — `agent/kb_lookup.py` + `tests/test_kb_lookup.py`. The risk-bearing piece. Verify the embedding architecture works against the existing 7 KB files before writing new content.
2. **D1** — `scripts/rebuild_kb_index.py`. Offline indexer. Can run in parallel with D2.
3. **D3 + D4** — `knowledge/install.md` + `knowledge/providers.md`. ~500 lines of writing. First 100 lines are the most important.
4. **D5** — Expand `knowledge/gateway.md` if D7 needs it (deferred until D7 implementation).
5. **D6** — System prompt update. 1 paragraph.
6. **D7** — `auxilium_wizard_handler.py` + `auxilium_wizard.py` + wiring in `ui/window.py`. ~300 lines.
7. **D8** — `tests/test_auxilium_tier1.py`. ~150 lines.
8. **ARCHITECTURE.md** — Update §3 and §13 in the same commit as the code.

D2 ships as a separate PR (architectural verification). D7 ships as a second PR (UI work). D3/D4/D6/D8 ship with whichever PR is more convenient.

---

## What's next

When this SPEC is approved and Phase 1 ships, the next deliverable is `SPEC-auxilium-tier-2.md` (the help-assistant tier). Tier 2 SPEC content will be shaped by what Phase 1's real-user testing reveals about which questions the KB lookup answers well and which it doesn't.

**Captain decision points:**
1. Approve the 10 acceptance criteria as the DONE bar?
2. Approve the two-PR split (D2 first as architectural verification, D7 second)?
3. Approve writing `install.md` and `providers.md` in this work?
4. Approve `gateway-setup.md` deferred to Phase 1.5?
