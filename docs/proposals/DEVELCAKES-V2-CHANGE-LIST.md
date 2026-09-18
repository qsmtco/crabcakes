# DevelCakes — v2 Change List

**Date:** 2026-09-17
**Author:** Lt. Qrusher (per PM direction)
**Status:** Planning — nothing implemented; read-only investigation only
**Source repo:** `/home/q/projects/crabcakes` (HEAD at time of writing)
**Successor:** DevelCakes — a hard fork, own repository, v1 preserved

> Consolidates a working session: the PM's change list, the code-grounded commentary on each
> item, prerequisites, and suggested additions. This is the input for a spec, not a spec.

---

## 0. Fork mechanics (do this first)

| Step | Action |
|---|---|
| 1 | `git tag -a v1.0 -m "Crabcakes v1" && git push origin v1.0`, then cut a GitHub **Release** — freezes v1 immutably |
| 2 | Create the new repo (`repo slug: develcakes`, display name "DevelCakes") |
| 3 | `git checkout -b v2 v1.0 && git remote add devl git@github.com:qsmtco/develcakes.git && git push devl v2:main` |
| 4 | Archive the Crabcakes repo once DevelCakes deploys (read-only, permanent) |

**Name — decided: `develcakes`.** `devel` is the established abbreviation for development
(Debian/RPM `-devel` packages, FreeBSD `devel/`, Gentoo `dev-*`). `devl` drops a vowel and reads
as a typo of "devil" or "dev". The `-cakes` suffix signals lineage without implying the same tool.

**What does NOT carry over to a new repo:** GitHub Actions secrets, branch protection, webhooks,
deploy keys, environments, issues/PRs/discussions, stars. PAT allowlist may 403 until the new repo
is added (prior precedent: API push ≠ git push).

**Rename footprint — the name is in runtime paths, not just git.** These must diverge at the fork
point or v1 and v2 will fight over the same files:

- `com.crabcakes.app` — GTK application id + desktop entry
- `~/.config/crabcakes/` — conversations, audit log, agent YAMLs
- `<repo>/.crabcakes/` — feed, tasks, prompts, secrets
- Package/manifest names, CI references, docs, agent skills/memory referencing the old path

---

## 1. The change list

### 1.1 Multi-coder / multi-debugger (parallelism)

**Already documented as blocked.** `agent/special_agents.py` states it directly: session keys
default to `special:<role>`, so same-role agents **collide and one replaces the other** — and
`role` selects the prompt template (`agent/context.py` `build_system_prompt`), so role cannot be
changed to dodge it. The documented fix is an explicit `session_key:` per agent YAML.

Deltas:

- Roster (`team.json` + per-agent YAML): distinct `session_key`s (`special:coder-1`, `coder-2`, …);
  roles unchanged so prompts still resolve.
- **Per-agent turn concurrency** in the runtime. Today a single "turn in flight" gate exists (the
  CLI nudge refuses on it). N agents needs a scheduler plus per-session locks.
- **Work claiming** — a claim/lease on work units, or N coders collide on the same spec.
- **N× the memory ratchet.** The widget-ratchet work (`SPEC-MEMORY-WIDGET-RATCHET`) becomes a
  prerequisite, not a nice-to-have: measured +4.5 MB/min and ~56 KB per retained card widget,
  never returned. N agents multiplies it.
- **N× feed volume** — already 15k cards with one team; retention/filtering becomes mandatory.
- Adjudication must attribute findings to a source agent, or re-litigation risk multiplies.

### 1.2 HTML chat surface

- Not a new idea: `docs/proposals/WEBKIT-RENDER-SURFACE_PROPOSAL.md` ("the agent speaks HTML")
  already exists. **Adopt or amend it — do not re-invent.**
- Replaces/extends `ui/views/chat_bubble.py` + `ui/handlers/chat_render_handler.py`; the GTK feed
  can remain.
- **Injection becomes a new risk class** — HTML from agent output needs sanitization and
  JS-off-by-default before it ships.
- Prereq: the ratchet fix (the proposal explicitly supersedes feed virtualization).

### 1.3 JEV routing → group chat

- Today routing is caller-decided: `ui/handlers/collab_handler.py` owns `ask` / `delegate` /
  `stop` / `tell` as pure pass-through; `ChatHandler` performs the routing. JEV turns that into a
  **Choice over the roster** (255 options — ample), with a confidence threshold and a fallback.
- **Group chat is the largest structural change in this list.** Conversations are per-session
  files today (`special:<agent>.json`). A shared transcript with per-agent attribution is a new
  data model, not a tweak.
- Needs: addressing/@mention semantics, an HTTP client for `/api/alpha/decisions`, a cost/latency
  budget, and **fail-open-to-human** on 429/529.

### 1.4 JEV completion detection (is a conversation between two agents done?)

- Feasible, but requires a **definition of "complete" per conversation type** — coder↔debugger
  audit loop, coder↔supervisor sendback — or the detector has no ground truth.
- Wiring: on complete → close the loop, write the audit row, notify Supervisor/PM.
- **Advisory only.** A false "complete" ends an audit loop early, which is the most expensive
  failure available. Sort, don't decide.

### 1.5 Telegram remote-in to the Supervisor

- `gateway/client.py` already exists — but it is a **WebSocket client for the OpenClaw gateway**
  with Ed25519 device auth. Decision required: reuse that transport, or build a first-class
  Telegram bot (Hermes already runs one that can be mirrored).
- **Model the contract on the CLI nudge**: strict argument shape, defined exit codes, delivery
  verified by audit row + feed card (hash-matched).
- **Security is the gating item** — this is remote command execution into a system that runs shell
  commands. Single-user allowlist, no free-form relay, kill switch, audited identically.

---

## 2. Prerequisites and ordering

Dependencies, not phases:

```
ratchet fix  →  rename/fork  →  HTML surface  →  multi-agent roster + per-agent concurrency
             →  group chat data model  →  JEV routing  →  JEV completion  →  Telegram
```

Rationale: multiplying agents before fixing the ratchet multiplies the leak; group chat before
feed retention makes the primary UI unusable; JEV routing before the roster exists has nothing to
route over.

---

## 3. Suggested additions

### 3.1 Do these three — cheap now, expensive later

1. **Log every JEV verdict** — decision, confidence, input hash, timestamp, and what the system did
   with it. Costs fractions of a cent; without it thresholds cannot be tuned and automated routing
   decisions cannot be explained later. With it, you have a dataset.
2. **Per-agent cost metering** — N coders × N debuggers × LLM × JEV loses the thread of spend
   within a day. Per-agent counters in the UI plus a daily rollup.
3. **A `git worktree` per coder** — multiple agents in one working tree will clobber each other.
   One worktree per agent; merges through a controlled gate.

### 3.2 Decide before building

4. **Agent attribution in git** — commit trailers (`Agent: coder-2`) plus feed card origin. Manual
   attribution is already expensive (the change-order exercise); with N agents it is untenable.
5. **Transcript durability** — `agent/persistence.py` uses `open(path,"w")` + `json.dump`
   (non-atomic; readers already tolerate torn files). A shared transcript makes that a daily event.
   Move to append-only JSONL or SQLite first.
6. **Feed retention + per-agent filtering before group chat** — 15k cards with 3 agents and card
   updates already being dropped. The feed is the product.
7. **A fallback router** — `/api/alpha/decisions` is alpha and versioned by date; JEV is now in the
   routing path. Keep a dumb fallback (round-robin/keyword) and the thresholds in a versioned
   config file, so degradation is graceful.

### 3.3 Nice to have

8. **A replay harness** — re-run a recorded transcript against a new prompt/roster/model and diff
   the outcome. The only way to tune prompts and JEV thresholds without shipping blind.
9. **A stop-all** — one action halting every agent. Per-command `stop` exists; N autonomous
   writers on a live repo need a big red button.
10. **One-writer-per-file as a stated invariant** (alongside "one auditor per artifact").
    Multi-agent systems fail on resource contention, not intelligence.
11. **Telegram as a digest console, not a firehose** — route only JEV-triaged NEEDS-PM items, with
    the CLI-nudge-style delivery contract. A raw feed mirror gets muted within a week.

**Caution:** group chat is a new artifact class and artifacts accumulate. Set a transcript
retention policy on day one, or DevelCakes inherits Crabcakes' doc sprawl plus a chat log.

---

## 4. Open decisions

| # | Decision | Notes |
|---|---|---|
| 1 | Telegram transport: reuse OpenClaw gateway client vs. first-class bot | `gateway/client.py` exists but targets OpenClaw + Ed25519 device auth |
| 2 | Group-chat transcript model: shared log w/ attribution vs. per-session + index | Determines the migration cost |
| 3 | "Complete" definitions per conversation type | Required before JEV completion detection is meaningful |
| 4 | JEV confidence thresholds + what happens below them | Policy, not code — belongs in versioned config |
| 5 | Does v2 keep the GTK feed, or does the HTML surface subsume it? | Affects how much of `ui/views/` survives |

---

## 5. Removals (PM directive)

Four things go. Counts below are from the live tree, excluding the `.crabcakes/tmp/uiresp2-audit/`
snapshot (a full copy of the tree that will mirror every removal and pollute every grep — delete it).

### R1. OpenClaw WebSocket / gateway client — **complete removal**

Delete the transport and everything that exists only to serve it:

| Target | Why |
|---|---|
| `gateway/client.py`, `gateway/__init__.py` | The WebSocket client itself (OpenClaw v3 device-auth protocol, Ed25519) — delete the package |
| `ui/handlers/gateway_handler.py` | Owns `GatewayClient` + `AgentManager` + connection lifecycle |
| `ui/handlers/connection_sync_handler.py` | Owns the post-connect wiring that injects live `GatewayClient`/`AgentManager` into dependent handlers — the indirection dies with it |
| `ui/handlers/chat_handler.py` | `_gw`, `set_gateway_client()`, `gateway_client` ctor param; sending currently goes through `self._gw.send_message()` — needs a local send path |
| `ui/handlers/review_handler.py` | Holds a gateway client for sending messages to agents |
| `ui/window.py` | GatewayHandler wiring, `set_gateway_client(None)`, the lambda-to-avoid-stale-None shim |
| `utils/config.py` | `get_gateway_url()`, `get_identity_dir()` (OpenClaw Ed25519 identity) |
| `models/activity.py` | Activity types are documented as "the exhaustive list from the gateway event catalog" — redefine locally |
| `agent/runtime.py` | `app_title` documented as flowing from gateway `displayName` |
| `agent/tools.py`, `ui/views/agent_builder.py`, `ui/views/auxilium_wizard.py`, `ui/handlers/auxilium_wizard_handler.py`, `ui/views/left_panel.py`, `utils/project_awareness.py`, `utils/prompt_loader.py` | Residual OpenClaw references |
| `tests/test_gateway.py`, `test_gateway_handler.py`, `test_connection_sync_handler.py`, `test_low345_gateway_hardening.py` | Retire with the code; `test_config.py`, `test_tools.py`, `test_kb_lookup.py` need partial edits |

**RETAIN — the Connect button.** `ui/toolbar.py` keeps `self._connect_btn` (label "Connect"), its tooltip,
the connection status label, and the state machine that renders `● Connecting` / `● Connected`. It is
**repurposed as the Telegram on/off control** — relabel and rewire the action to the Telegram transport
(§1.5). Do not delete the widget or its states; only the thing it talks to changes.

### R2. Pango markup → HTML

242 markup call sites across ~20 source files. Densest:

| File | Sites |
|---|---|
| `ui/views/chat_bubble.py` | 33 |
| `utils/escaping.py` | 32 |
| `ui/views/feed_card.py` | 22 |
| `utils/markdown.py` | 14 |
| `utils/gtk_safe_link.py` | 14 |
| `ui/views/main_content.py` | 11 |
| `ui/handlers/chat_render_handler.py` | 10 |
| `ui/views/session_menu.py`, `file_tree.py`, `chat_input_toolbar.py` | 6 each |
| `utils/syntax_highlight.py`, `ui/views/feedbar.py`, `ui/toolbar.py` | 5 each |
| `ui/views/diff_card.py` | 3 |

This is not a find-and-replace — it replaces the **back half of the render pipeline**:
`markdown → escaping → Pango markup → GtkLabel.set_markup` becomes `markdown → sanitize → HTML → WebKit`.
`utils/markdown.py`, `utils/escaping.py`, `utils/gtk_safe_link.py` and `utils/syntax_highlight.py` are
either replaced or reduced to sanitizers. Tests to retire/replace: `test_pango_guard_sites.py` (47
sites), `test_escaping.py`, `test_markdown.py`, `test_gtk_safe_link.py`, `test_chat_render_handler.py`,
`test_diff_viewer.py`, `test_main_content_settings_bar.py`, `test_uirsp3_phase2.py`.

**Risk, stated plainly:** `test_pango_guard_sites.py` exists because markup injection was a real bug
class here. Swapping to HTML **moves** that risk, it does not remove it — the equivalent guard
(HTML sanitization, JS off by default) must be rebuilt in the same change, not after.

### R3. Slash commands — remove most

Current surface:

- `ui/handlers/collab_handler.py` — `/ask`, `/delegate`, `/stop`, `/tell` (all pure pass-through; routing
  is done by `ChatHandler`)
- `ui/handlers/command_handler.py` — dispatch
- `ui/handlers/agent_command_handler.py` — agent-issued commands (max 3 per response)
- `models/command.py` — `Command` / `CommandResult`

`/nudge` is a **CLI argument, not a slash command** — it stays (it is the verified relay contract).

Decision to make: with a group chat, `@coder-2 do X` in natural language makes `/ask`, `/delegate` and
`/tell` redundant — the JEV router (§1.3) replaces their addressing role. **`/stop` should survive**
as the safety path (and pairs with the stop-all in §3.3). Removing the four collapses `collab_handler.py`
plus much of `test_command_handler.py` and `test_agent_command_handler.py`.

### R4. feedbar — remove

- `ui/views/feedbar.py` — the Response Status bar (`set_status_text` → `set_markup`,
  `set_progress_fraction`, `set_progress_hidden`)
- `ui/handlers/activity_handler.py` — the 6-state activity machine takes feedbar as a constructor
  dependency and calls `_update_feedbar()` throughout; its rendering half goes with the widget
- `ui/window.py` — `from ui.views.feedbar import FeedBar`, `self._response_status = FeedBar()`, and the
  `feedbar=` construction argument

**Not purely subtractive.** The activity state machine also drives the streaming label, the 250 ms ticker
and the `_live_update` elapsed bucket — the exact surfaces `SPEC-MEMORY-WIDGET-RATCHET` touches. Removing
feedbar means deciding where activity state surfaces instead (presumably the HTML surface). Decide that
before deleting, or the ticker is left writing to a widget that no longer exists.

---

## 6. Provider changes — dictation STT and the Improve button

Both verified live against OpenRouter (not read from docs).

### 6.1 Dictation ("prompt") button → OpenRouter STT, remove all local STT

**Target:** `mistralai/voxtral-small-24b-2507-stt` — **confirmed working.** Note the id is *not* in
`/api/v1/models` (same pattern as the decisions endpoint); it must be used verbatim. The chat model
`mistralai/voxtral-small-24b-2507` is rejected by the transcriptions endpoint with "does not exist",
so the `-stt` suffix is not optional.

**Endpoint and shape** (learned by probing; `format` is required):

```
POST https://openrouter.ai/api/v1/audio/transcriptions
{ "model": "mistralai/voxtral-small-24b-2507-stt",
  "input_audio": { "data": "<base64 audio>", "format": "ogg" } }
→ { "text": "…", "usage": { "seconds": 4.416, "cost": 0.0002208 } }
```

Round-trip verified: synthesized speech in → `"Eagle Dispatch, Truck 15, dumping at the landfill."`
out, $0.00022 for 4.4 s (~$0.003/min). Alternatives that also work: `mistralai/voxtral-mini-transcribe`
($0.0002, and it returns token counts) and `openai/whisper-1` ($0.0005, ~2× the cost).

**Remove:**

| Target | Note |
|---|---|
| `utils/stt.py` | faster-whisper engine, `arecord`/ALSA capture, Hugging Face model download, `STT_MODEL_SIZE` allowlist + `_VALID_MODEL_SIZES` |
| `ui/handlers/media_handler.py` | the `from utils.stt import STTEngine` call site and its GLib dispatch |
| `tests/test_low6_8_9_10_11.py` | the LOW-6 model-size validation tests become moot |
| `tests/test_architecture.py` | drop the `stt.py` entry |

**Capture stays.** The microphone path (`arecord` / PipeWire at 16 kHz mono) is still needed — audio is
captured locally and then uploaded. What disappears is the local *transcription* engine and its model
download, not the capture.

**Two consequences to accept deliberately:**

1. **Audio leaves the machine.** Local STT meant voice never left the box; this sends it to OpenRouter →
   Mistral. That is a privacy posture change and belongs in the threat model, not just the changelog.
2. **Dictation now depends on network + key + quota.** Needs a clear failure path (no network, 429,
   invalid key) and reuses the existing OpenRouter credential store rather than a new secret.

### 6.2 "Improve" button → `google/gemini-2.5-flash` on OpenRouter

**Target:** `google/gemini-2.5-flash` — confirmed present in the OpenRouter catalog (alongside
`-lite`, `-image`, and `:batch` variants).

**Change:** `utils/improve.py` currently calls the **MiniMax** API — it reads
`~/.config/crabcakes/config.json` (`apiKey`, `baseUrl`, `model`) and the system template from
`prompts/system/improve.md`. Repoint it at OpenRouter chat completions with `google/gemini-2.5-flash`
and the existing OpenRouter key; the prompt template and the improve callback contract stay as they are.

**Retain:** the `_NoAuthRedirectHandler` in `utils/improve.py` that strips the `Authorization` header on
cross-host redirects — that is a real protection and must survive the provider swap.

---

## 7. Reference — JEV facts established this session

- Model: `typesafe/jev-1.13` on OpenRouter (versioned id required; `jev-latest` is rejected there).
  Resolved build observed: `typesafe/jev-1.13-20260917`.
- Endpoint: `POST https://openrouter.ai/api/alpha/decisions` — **not** chat/completions, which
  rejects it with "this is a decisions model".
- Body: `{ model, state: string|object|array, questions: { <id>: { type: choice|score|noul,
  instructions, criteria } } }`.
- Returns typed answers with probabilities and `confidence`, plus usage and cost.
- Primitives: **Choice** (one of a set), **Score** (ordered rubric), **Noul** (P(yes), 0–1).
- Measured live: 0.24 s and $0.0000178 for a 3-question call (424 input tokens) — ~18× faster and
  ~96× cheaper than the recorded Gemini baseline on the same questions, and it reported confidence
  0.43 where the LLM claimed 0.82.
- Boundaries: no text generation at all, text-only input, 64k context, English strongest; TypeSafe's
  own docs say explicitly "not agents". Calibration is not externally proven — tune thresholds
  before trusting a value.
