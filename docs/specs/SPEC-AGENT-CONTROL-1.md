# SPEC: Agent Control — Status Report, Nudge Channel, and Auto-Resume

**Date:** 2026-09-11
**Author:** Supervisor (per PM direction following the 2026-09-11 stalled-pipeline investigation)
**Revision 2 (2026-09-11, PM decisions folded):** nudge is **Supervisor-only**; cron stall alerting **approved**; content policy set (message bodies only, never tool I/O); **auto-resume moved into scope as Phase 3**.
**Status:** Draft v2 — PM decisions recorded in §11; awaiting implementation sign-off (§12)
**Depends on:** none (Phase 1 is additive and standalone). Phase 2 depends on Phase 1's reporter module. Phase 3 depends on Phases 1–2.
**Related:** `docs/specs/SPEC-UI-RESPONSIVENESS-2.md`, `docs/proposals/PROPOSAL-post-responsiveness-priorities.md`
**Target branch:** main (base `a3c95c2`)

> **Architecture compliance:** Phase 1 adds `utils/status_report.py` — pure Python, no GTK, no imports from `ui/`, read-only against existing files. The CLI shim `scripts/crab_status.py` follows the existing `scripts/rebuild_kb_index.py` precedent. Phase 2 touches only `main.py` (GApplication wiring) and routes into the existing `AgentRuntimeHandler.send_to_special_agent` (`ui/handlers/agent_runtime_handler.py:760`) — no new handler, no new layer, no handler-to-handler import. **Phase 3 adds no process to the app at all** — it runs inside the same CLI shim, invoked periodically by an external scheduler. **No new listening socket, no new daemon, no client that reconnects, at any phase.** Every phase works with the app closed (Phase 1) or open (Phases 2–3).

---

## DISCOVERY (Rule 1 — read before writing)

- Read `main.py` (57 lines): `CrabcakesApp(Gtk.Application)` is constructed at `:36` as `super().__init__(application_id='com.crabcakes.app')` — **no `flags=`**, and no `command-line` / `handle-local-options` handler. Under current behaviour a second invocation simply activates (focuses) the running instance.
- Verified the app **already owns `com.crabcakes.app` on the session bus** (`gdbus … ListNames` → `'com.crabcakes.app'`). GTK's GApplication single-instance + command-line forwarding is therefore already available; it is unused, not missing.
- `gdbus introspect --session --dest com.crabcakes.app --object-path /` returns only an empty `com` node — there is **no D-Bus control interface** today, and no action map.
- Read `ui/handlers/agent_runtime_handler.py`: `send_to_special_agent(self, session_key: str, text: str) -> None` at `:760` is the single entry point the chat box uses to start an agent turn. It performs the pre-loop preparation and calls `rt.send_message`. This is the correct target for a nudge — routing anywhere else would bypass turn tokens and the `_ended_sessions` discipline.
- Read `agent/persistence.py`: conversations persist to `<config>/conversations/<session_key>.json` (`conversations_dir()` `:28`). Session keys are `special:supervisor`, `special:coder`, `special:debugger` (observed on disk). **`save_conversation_to_disk` writes non-atomically** — `open(path, "w")` then `json.dump` at `:92-93` — so a concurrent reader can observe a truncated file. Any reader must tolerate `json.JSONDecodeError` (and it is worth noting separately: a crash mid-write loses that conversation's tail).
- Read `utils/feed_store.py`: the feed snapshot is written via `_atomic_write_json` (`.tmp` + `os.replace`), so **reads are consistent without taking the flock**. A status reader must NOT acquire the feed lock — `_acquire_lock` is a bounded-but-still-blocking flock and the app holds it during compaction.
- Read `agent/runtime.py`: `TurnStatus` enum (`:120`) with `RUNNING`/`STREAMING` non-terminal and `COMPLETED`/`FAILED`/`CANCELLED` terminal; accessors `get_turn_state(session_key)` (`:1942`) and `get_last_turn_result` (`:1917`) exist and are exactly what Phase 2's refuse-when-busy guardrail needs — and what Phase 3's resume eligibility check needs.
- Verified observability sources already on disk (used by hand during the 2026-09-11 investigation): `~/.config/crabcakes/conversations/*.json`, `~/.config/crabcakes/audit-log.jsonl` (4,064 entries; `{tool_name, args_hash, approved, timestamp}`), `.crabcakes/feed.json` (10,170 cards, 15.5 MB at the time of writing; **3,135 cards / 4.1 MB after the UIRESP2 Phase 1–3 pruning landed**), `.crabcakes/tasks.md`, `/var/crash/*.crash` (apport; carries `Signal`, `ProcCmdline`, `Date`, `ProcMaps`).
- Verified **no** existing path for any of these capabilities: no agent-control API (the only listener is the KB server `kb_server.py:248` — `/health`, `/agents`, `/v1/chat/completions`), no CLI subcommands, no D-Bus actions, no filesystem inbox, and no Wayland input tooling installed (`xdotool`/`ydotool`/`wtype`/`dotool` all absent).
- Architecture owner: `main.py` owns GApplication lifecycle; `ui/handlers/agent_runtime_handler.py` owns turn submission; `utils/` owns pure read-only helpers.

---

## 1. Overview

### 1.1 Problem

The agent pipeline can stall in ways that are invisible from outside the app. On 2026-09-11 the Coder's turn ended silently — last message *"Confirmed the bug. Writing the **red tests first**."*, no tool call following — and the pipeline sat idle for 3.5 hours. Diagnosing it required reading the process table, three conversation JSON files, the 15 MB feed, the audit log, git state, and `/var/crash` **by hand**.

There is no supported way to (a) ask the app what it is doing, (b) deliver a message to an agent without a human at the keyboard and a mouse on the right tab, or (c) recover automatically from a stall once it is detected.

### 1.2 Solution

Three capabilities, all built on things that already exist:

- **Phase 1 — `crabcakes-status`:** a read-only reporter over the files the app already writes. Works whether the app is running or closed, headless, no GTK. Detects the specific stall classes (turn ended without a tool call, blocked on a sendback, main thread pinned).
- **Phase 2 — `--nudge`:** a command-line entry that forwards a message to the **Supervisor** through GTK's built-in GApplication single-instance channel (the session bus the app already joins) and into the existing `send_to_special_agent`. No socket we own, no daemon, no reconnect loop.
- **Phase 3 — `--auto-resume`:** the reporter is invoked periodically by the PM's scheduler; when it detects a *resumable* stall (the 2026-09-11 shape) and every guardrail in §4.3 passes, it delivers a **templated** resume nudge to the stalled session. Bounded by attempt, cooldown, and daily caps, disabled by default, and fully logged. **It never answers an approval, and it never resumes a stall that is waiting on a human decision.**

### 1.3 Scope

| In | Out |
|---|---|
| `utils/status_report.py` — pure collector/renderer | Any new network listener or HTTP API |
| `scripts/crab_status.py` — CLI shim (`--json`, `--no-content`, `--full`, `--project`, `--auto-resume`, `--watch`) | Modifying `agent/runtime.py` turn semantics |
| `main.py` — `HANDLES_COMMAND_LINE`, `--nudge` (Supervisor only), `--status` | Remote/over-network control of the app |
| Cron wiring for `crab_status.py --json` (§2.4) | Auto-answering approvals (permanently out — §9) |
| **Auto-resume of `turn_stalled` (§4)** | Auto-resume of `blocked_on_sendback` (deliberately deferred — §9) |
| Guardrail + audit-trail plumbing for nudges and resumes | Phase 4 file-inbox (fallback only) |
| Tests for all phases (headless) | Any long-running process added to the app |

### 1.4 Principles

- Read-only by default; the reporter never mutates app state and never takes the feed flock.
- No new listening socket, no daemon, no long-lived client. Phase 3 is a **periodic invocation**, not a watcher process.
- Same-user, session-scoped only — the same trust boundary as `systemctl`.
- Every mutation of agent state must be **visible**: a nudge or a resume appears in the feed and the audit log, with its origin.
- **Autonomous action requires a hard bound.** Any automatic behaviour has an attempt cap, a cooldown, a daily cap, and a kill switch. An unbounded retry loop is the failure mode we are trying to prevent, not a feature.
- Failure is loud and returns a non-zero exit code — never a silent no-op.

---

## 2. Phase 1 — Status report

### 2.1 `utils/status_report.py` (new)

Pure module, no GTK, no `ui/` imports. Public surface:

```python
def collect(project_path: str, config_dir: str | None = None) -> dict:
    """Gather the raw status dict. Never raises; degrades per-section."""

def render_text(report: dict, *, show_content: bool = False) -> str: ...
def render_json(report: dict) -> str: ...
def assess(report: dict) -> tuple[str, int]:
    """Return (summary_line, exit_code). 0 = healthy, 2 = needs attention, 3 = app down."""
```

**Sections and sources**

| Section | Source | Notes |
|---|---|---|
| `app` | `/proc/<pid>` for `main.py` | pid, uptime, RSS, thread count; two-sample CPU over ~1 s |
| `app.main_thread` | `/proc/<pid>/task/<pid>/stat` + `wchan` | `idle` (state S, poll) vs `busy` (state R, >80 % for both samples) — distinguishes "idle" from "spinning" |
| `work` | newest `.md` in `docs/specs/`, `.crabcakes/tasks.md`, `git status --porcelain`/`rev-list` | current unit, statuses, dirty/unpushed counts |
| `agents` | `<config>/conversations/*.json` | per session: mtime, last role, last message head (truncated), message count, model |
| `activity` | `.crabcakes/feed.json` (tail) | last N cards: timestamp, source, title |
| `approvals` | `<config>/audit-log.jsonl` (tail) | approvals in the last window; grants vs denials |
| `health` | `/var/crash/*.crash` with `Date` > app start | signal, `ProcCmdline` |

**Stall heuristics (the point of the tool).** `assess()` emits a warning per detected class:

1. **`turn_stalled`** — for any session: last message role is `assistant`, no tool result follows it, `now - file_mtime > threshold` (default 10 min), and **no repo writes since that message.** This is precisely the 2026-09-11 failure. **This is the only class Phase 3 may act on.**
2. **`blocked_on_sendback`** — a `*SENDBACK*.md` exists in `docs/specs/` newer than the newest commit, and no commit has touched the locked files since. Means "an audit rejected work and nobody has picked it up". **Detected and alerted, never auto-acted (§9).**
3. **`app_spinning`** — main thread `busy` per the table above (the pre-fix freeze signature).
4. **`approvals_pending`** — ≥3 approval entries in the last 30 min with no file writes after them. **Also a hard veto for Phase 3 (§4.3 G1).**
5. **`crash_after_start`** — a crash report whose `Date` is after the running app's start time.

**Read-safety requirements (must be tested):**

- Tolerate `json.JSONDecodeError` on any conversation file — `save_conversation_to_disk` is non-atomic (`agent/persistence.py:92`). On parse failure, report the file as `unreadable (writer active)` and continue.
- Never call `feed_store._acquire_lock`. Feed reads are safe because writes are atomic (`os.replace`).
- **Content policy (PM decision, §11.3).** Message *bodies* are truncated to 120 chars by default. `--full` raises the cap **for message bodies only** — agent and user text — to 2,000 chars per message. **Tool arguments, exec commands, and tool/command outputs are never rendered in full at any verbosity level**; only the tool *name* is reported. These fields are where secrets land (raw commands in `tool_args`, keys in outputs) and they are not where the diagnostic value lives: the 2026-09-11 stall was fully diagnosable from the agent's 48-character last sentence. Rationale: the report's audience is the PM's terminal and phone, not a place for project content or credentials.
- Cache the parsed feed summary in `<cache>/crabcakes/status-feed.json` keyed by `(path, size, mtime)` — `feed.json` was 15.5 MB at spec time and full parse costs ~0.3 s. Target: **whole report < 1 s**.

### 2.2 `scripts/crab_status.py` (new)

Thin CLI over the module:

```
crab_status.py [--project PATH] [--json] [--full] [--no-feed] [--watch N]
               [--auto-resume]
```

- Default: human-readable report (the format demonstrated in §1 of the 2026-09-11 investigation write-up).
- `--json`: machine-readable, for cron/alerting.
- `--auto-resume`: enables the Phase 3 action path for this invocation (§4). Without it, the CLI is **strictly read-only**, even if a stall is detected.
- Exit codes: `0` healthy, `2` attention needed (any stall class fired), `3` app not running (report still emitted for the filesystem side).

### 2.3 Invariants

1. Phase 1 changes nothing the app writes and never imports GTK.
2. Report generation is correct with the app **closed**.
3. No lock is ever taken on `feed.json`; a report cannot block or be blocked by the app.
4. A truncated/unreadable input degrades one section, never the whole report.
5. `assess()` returns `2` for the exact 2026-09-11 shape (assistant-final message, no tool call, no writes, > threshold).
6. **Read-only means read-only:** with `--auto-resume` absent, no invocation of this tool can mutate anything, regardless of what it detects.

### 2.4 Cron stall alerting (PM decision, §11.2 — approved)

`crab_status.py --json` is designed for a scheduler. The PM wires it to the existing Hermes cron facility (the same one already used for site monitors); **no new scheduler is introduced**.

- **Cadence:** every 15 min.
- **Alert condition:** exit code non-zero (`2` attention, `3` app down).
- **Dedupe (required):** alert on *state change* only — healthy → attention. While a stall episode persists, re-alert at most once per hour for that same episode. Episode identity and last-alert timestamp persist in `<cache>/crabcakes/status-state.json`, keyed by the same episode id Phase 3 uses (§4.4). Without this the tool becomes a 96-message-per-day nuisance and gets muted, which defeats it.
- **Delivery:** the summary line plus the detected class and named agent/session — never the full report.
- **Silence is the default:** a healthy pipeline produces no message.

---

## 3. Phase 2 — Nudge channel

### 3.1 `main.py` — enable command-line forwarding

```python
from gi.repository import Gio, Gtk

class CrabcakesApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id='com.crabcakes.app',
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.connect('activate', self.on_activate)
        self.connect('command-line', self.on_command_line)

    def on_command_line(self, app, command_line) -> int:
        argv = command_line.get_arguments()[1:]
        # --status  → run utils.status_report headless and print to the caller's stdout
        # --nudge @Supervisor "text" → validate, then deliver to the running instance
        ...
        command_line.set_exit_status(code)
        return code
```

GTK routes a second invocation's arguments to the **running** instance via the session bus and exits the second process. That is the entire transport: no socket of ours, no daemon, no reconnect.

**Critical detail — do not silently start a GUI on a nudge.** With `HANDLES_COMMAND_LINE`, launching `main.py --nudge …` when no instance is running would start one. The handler must check `self.get_is_remote()`:

- `--nudge` + not remote → print `crabcakes is not running; start the app first` and return `4` **without** presenting a window.
- `--status` + (not remote or remote) → run Phase 1 headless and return — status must work with the app closed, which is a feature, not a workaround.

### 3.2 Routing

- Argument form: `--nudge @<Agent> "<text>"` (mirrors the existing `/ask @Agent "…"` convention documented in `prompts/system/collab.md`).
- **Reach: `@Supervisor` only (PM decision, §11.1).** The target is validated against a single-element allowlist; `@Coder`, `@Debugger`, `@Auxilium`, and any unknown agent are refused with exit `3` and a message naming the permitted target. The Supervisor is the orchestrator — it can address the other agents through the normal in-app collaboration path, so direct CLI reach into Coder or Debugger buys nothing and widens the blast radius.
- Agent → session key: `@Supervisor` → `special:supervisor` (lowercase).
- Delivery: build the concrete `AgentRuntimeHandler` for that session and call `send_to_special_agent(session_key, text)` — the same path the chat box uses, so turn tokens, `_ended_sessions`, and the pre-loop preparation all behave identically.

### 3.3 Guardrails (required, not optional)

| Guardrail | Behaviour |
|---|---|
| **Reach** | `@Supervisor` only. Any other target → exit `3`, no dispatch (§3.2) |
| Payload cap | 4,096 chars (matches the `/ask` cap in `project-awareness.md`) → exit `5` |
| Turn in flight | Refuse if `rt.get_turn_state(sk)` is `RUNNING`/`STREAMING` (`agent/runtime.py:1942`, `:120`) → exit `2`, message `turn in flight for <agent>; retry when idle` |
| Session must exist | Refuse if the conversation is not already loaded/persisted → exit `6`; require an explicit `--create` to make one |
| Same user only | Inherent: the session bus is per-user. Document it; do not add a bypass |
| **Audit trail** | Every nudge writes (a) a feed card showing the text and target, and (b) an `audit-log.jsonl` record `{origin: "cli-nudge", target, chars, text_sha256[:16], timestamp}` — the hash, not the raw payload |
| **Visibly distinct from PM input** | The injected feed card carries `metadata["origin"] = "cli-nudge"` and renders a visible origin marker (e.g. `via CLI`). A nudge must NEVER be indistinguishable from a message the PM typed — the PM has to be able to tell, at a glance in the feed, which turns they authored and which arrived through this channel |
| Visible in the UI | The injected message renders in the target tab exactly as a typed message does, apart from the origin marker above |

Exit codes: `0` delivered · `2` refused (turn in flight) · `3` unknown/unauthorised agent · `4` app not running · `5` payload too long · `6` no such session.

### 3.4 Invariants

1. No new listening socket, port, or daemon is created by any phase.
2. A nudge is never delivered silently — feed card + audit record always accompany it.
3. A nudge cannot interleave with a running turn.
4. `--nudge` with the app closed never starts a GUI.
5. Phase 2 cannot be reached by anything but a same-user local process.
6. **The only reachable target is the Supervisor.**

---

## 4. Phase 3 — Auto-resume (PM decision, §11.4 — IN SCOPE)

### 4.1 What it does

Invoked periodically (`crab_status.py --auto-resume`), the tool re-runs the Phase 1 assessment, and — **only** when it detects a `turn_stalled` episode and every guardrail in §4.3 passes — delivers a templated resume nudge to the stalled session through the Phase 2 transport.

It is **not** a daemon and adds **no code to the app**. State lives in a small JSON file, so each invocation is self-contained and idempotent.

### 4.2 Resume message

The text is a **fixed template**, never free text, never model-generated:

```
[auto-resume] Your previous turn ended without a tool call and the pipeline has been
idle for <N> minutes. Resume the work described in your last message, or state
plainly why you cannot continue. Attempt <k> of <max>.
```

Rationale: a templated payload cannot be influenced by whatever happens to be in the conversation, cannot be repurposed as arbitrary instruction injection, and is self-identifying in the transcript.

### 4.3 Guardrails (all must pass; any failure → no action, and the reason is reported)

| ID | Guardrail | Behaviour |
|---|---|---|
| **G1** | **Never resume past a pending human decision** | Veto if `approvals_pending` fired, or the session's last card is an approval request, or the stalled turn's final message is an approval prompt. An approval gate exists to be answered by a human; auto-resuming through it would defeat the control and is the single most dangerous failure mode. Unconditional |
| **G2** | **Detected class must be `turn_stalled`** | `blocked_on_sendback`, `app_spinning`, and `crash_after_start` are alert-only (§9) |
| **G3** | **Disabled by default** | Acts only when `--auto-resume` is passed. Absent the flag, the tool is read-only (§2.3.6) |
| **G4** | **Attempt cap per episode** | Max **2** resume attempts per stall episode, then stop and alert |
| **G5** | **Cooldown** | ≥10 min between attempts for the same episode |
| **G6** | **Daily cap** | Max **6** resumes per rolling 24 h, project-wide, then stop and alert |
| **G7** | **Circuit breaker** | 3 consecutive resumes that produce no new agent activity within 15 min → auto-resume disables itself and alerts. Prevents an endless nudge/ignore loop |
| **G8** | **Turn must be genuinely idle** | Re-uses the Phase 2 in-flight check; refuse if `RUNNING`/`STREAMING` |
| **G9** | **Session and app must exist** | Refuse if the app is not running (exit `4`) or the session is not loaded (exit `6`) |
| **G10** | **Kill switch** | A single documented switch (env var or config key) disables Phase 3 without touching the scheduler |
| **G11** | **Full visibility** | Every resume writes a feed card with `metadata["origin"] = "auto-resume"` **and** attempt number, plus an `audit-log.jsonl` record `{origin: "auto-resume", target, episode_id, attempt, chars, text_sha256[:16], timestamp}` |
| **G12** | **Cost awareness** | A resume starts a real agent turn and consumes model quota — on the current config the Supervisor runs `zai/glm-5.3`, which bills against the PM's GLM Coding Plan. The caps in G4/G6 exist partly for that reason and should not be raised without accounting for it |

### 4.4 Episode identity

An **episode** is `sha256(session_key + last_message_timestamp + last_message_sha)[:16]`. It is stable across invocations while the stall persists, and changes the moment the agent produces new activity. Attempt counts, cooldowns, and last-alert times are keyed on it in `<cache>/crabcakes/auto-resume-state.json`. This is what makes G4/G5/G7 and the §2.4 alert dedupe work — without it, every invocation would look like a fresh stall.

### 4.5 Scheduling

The PM's existing scheduler runs `crab_status.py --auto-resume --json` every 5 minutes. Per invocation:

```
assess() → turn_stalled? ──no──→ alert path only (§2.4)
              │yes
              ▼
        G1 pending decision? ──yes──→ 🛑 no action, report why
              │no
              ▼
        G3 enabled? G8 idle? G9 exists? ──no──→ 🛑 no action, report why
              │yes
              ▼
        G4/G5/G6/G7 caps OK? ──no──→ 🛑 no action, report why
              │yes
              ▼
        deliver templated resume → feed card + audit record → update state
```

### 4.6 Invariants

1. Phase 3 never runs unless explicitly enabled (G3).
2. Phase 3 never acts on any class other than `turn_stalled` (G2).
3. Phase 3 can never answer, bypass, or pre-empt an approval (G1).
4. Every automatic action is bounded by attempt, cooldown, and daily caps, and is reversible via one switch (G4/G5/G6/G10).
5. Every automatic action is visible in the feed and the audit log with its origin and attempt number (G11).
6. Phase 3 adds no process, no timer, and no thread to the running app.

---

## 5. Phase 4 — fallback only (file inbox)

**Not in scope unless Phase 2's bus routing proves unreliable** (e.g. the app is launched from a context that is not on the user's session bus — SSH, systemd unit).

Design if needed: the app polls `.crabcakes/inbox/` on a 1 Hz GLib timer (reusing the activity ticker's pattern, `ui/handlers/activity_handler.py:641`), reads `*.json` payloads `{target, text, ts, id}`, applies the same guardrails, then moves each to `.crabcakes/inbox/done/`. Requires: adding a timer, adding `.crabcakes/inbox/**` to `_should_ignore` in `crabwatch_handler.py:47` so the watcher does not emit feed cards for the channel's own traffic, and a per-message id for idempotency. Costs more code and introduces polling; prefer Phase 2. Phase 3 depends on Phase 2's transport, so it inherits this fallback.

---

## 6. Data flow

```
Phase 1 (read-only, app may be closed)
  /proc/<pid>  ─┐
  conversations ─┤
  feed.json     ─┼─→ utils/status_report.collect() → render_text|render_json → exit code
  audit-log     ─┤
  git, /var/crash ┘
        └─→ scheduler (15 min) → alert on state change only (§2.4)

Phase 2 (app running)
  crab_status nudge ─→ main.py --nudge @Supervisor "…"       [second process, exits]
        └─ GApplication forwarding (session bus, already joined)
              └─ running instance: on_command_line
                    ├─ validate (Supervisor-only, cap, session, turn state)
                    ├─ feed card (origin=cli-nudge) + audit record (hash)
                    └─ AgentRuntimeHandler.send_to_special_agent(sk, text)
                          └─ rt.send_message → _run_loop (background thread)

Phase 3 (app running, scheduler-driven, opt-in)
  scheduler (5 min) ─→ crab_status --auto-resume
        ├─ assess() → episode id (§4.4) → state file
        ├─ guardrails G1–G10 (any failure → report only, no action)
        └─ pass ─→ same Phase 2 transport, templated text,
                   feed card (origin=auto-resume) + audit record
```

---

## 7. Test plan

All Phase-1 tests must run **headless and without GTK** (this also sidesteps the headless-GTK segfault class that produced the 11:55 crash report — GTK suites must use `xvfb-run -a`).

| Test | Phase | Asserts |
|---|---|---|
| `test_report_runs_with_app_closed` | 1 | Valid report; exit `3`; no exception |
| `test_turn_stalled_detected` | 1 | Fixture reproducing the 2026-09-11 shape → `assess()` returns `2` and names the agent |
| `test_turn_stalled_not_fired_when_tool_follows` | 1 | Same fixture + a trailing tool message → healthy |
| `test_truncated_conversation_json_degrades_only_that_section` | 1 | Non-atomic write artefact → section marked unreadable, report still emits |
| `test_report_never_acquires_feed_lock` | 1 | Monkeypatched `feed_store._acquire_lock` raises if called |
| `test_feed_summary_cached_by_mtime` | 1 | Second call does not re-parse |
| `test_blocked_on_sendback_detected` | 1 | Fixture with a newer `*SENDBACK*.md` than the newest commit |
| `test_content_truncated_by_default` | 1 | 120-char cap on message bodies |
| `test_full_flag_raises_message_cap_only` | 1 | `--full` raises message bodies to 2,000 chars **and still renders no tool arguments or command output at any level** (§2.1) |
| `test_alert_deduped_by_episode` | 1 | Second invocation with the same episode emits no alert; new episode does |
| `test_argv_parse_nudge_forms` | 2 | `--nudge @Supervisor "x"`, quoting, missing agent, oversized payload |
| `test_nudge_refused_for_non_supervisor_agent` | 2 | `@Coder` / `@Debugger` / `@Auxilium` / unknown → exit `3`, no dispatch (§3.2) |
| `test_nudge_refused_when_turn_in_flight` | 2 | With a fake runtime returning `STREAMING` → exit `2`, no dispatch |
| `test_nudge_logs_feed_card_and_audit_record` | 2 | Both artefacts written; audit record carries the hash, not the text |
| `test_nudge_card_is_marked_as_cli_origin` | 2 | Feed card carries `metadata["origin"] == "cli-nudge"` and renders the origin marker; a typed message does not |
| `test_nudge_does_not_start_gui_when_not_remote` | 2 | `get_is_remote()` False → exit `4`, no `present()` |
| `test_readonly_without_auto_resume_flag` | 3 | Stall fixture + no flag → zero mutations, no transport call (§2.3.6) |
| `test_resume_never_fires_when_approval_pending` | 3 | **G1.** `approvals_pending` fired, or last card is an approval request → no dispatch, reason reported |
| `test_resume_only_for_turn_stalled` | 3 | **G2.** `blocked_on_sendback` / `app_spinning` / `crash_after_start` → no dispatch |
| `test_resume_attempts_capped_per_episode` | 3 | **G4.** Third attempt for one episode → refused |
| `test_resume_cooldown_enforced` | 3 | **G5.** Second attempt inside 10 min → refused |
| `test_resume_daily_cap_enforced` | 3 | **G6.** Seventh resume in 24 h → refused, alert emitted |
| `test_resume_circuit_breaker_trips` | 3 | **G7.** 3 sterile attempts → auto-resume self-disables |
| `test_resume_episode_id_stable_then_changes` | 3 | Same stall → same id across invocations; new agent activity → new id |
| `test_resume_writes_feed_card_and_audit_with_origin_and_attempt` | 3 | **G11.** `origin == "auto-resume"`, attempt number present |
| `test_resume_message_is_template_only` | 3 | Payload matches the fixed template; no conversation content is interpolated (§4.2) |

Manual integration (documented, run once per phase): start the app → `main.py --nudge @Supervisor "ping"` → confirm the message appears in the Supervisor tab and both log artefacts exist. For Phase 3: seed a synthetic stalled conversation in a scratch project → run `--auto-resume` → confirm exactly one resume, correct caps on re-run, and correct refusal when an approval is pending.

---

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Capability escalation (nudge)** — an instruction into an agent with file-write and exec access | HIGH | Supervisor-only reach (§3.2); same-user/session-only; 4,096-char cap; refuse-when-busy; mandatory feed card + audit record; PM sign-off required before Phase 2 ships |
| **Capability escalation (auto-resume)** — an *automatic* instruction into the orchestrator, with no human in the loop | **HIGHEST** | Disabled by default (G3); templated payload only (§4.2); attempt/cooldown/daily caps (G4–G6); circuit breaker (G7); kill switch (G10); full audit with attempt numbers (G11); **hard veto on any pending approval (G1)** |
| **Auto-resume loop** — resume → agent stalls again → resume | HIGH | Episode identity (§4.4) + attempt cap (G4) + cooldown (G5) + circuit breaker (G7). Bounded by construction, not by luck |
| **Auto-resume burns quota** — each resume is a real agent turn on a metered plan | MEDIUM | G12 documented; daily cap (G6) defaults to 6 |
| Reporter blocks on the feed lock | MEDIUM | Reporter never locks; reads rely on atomic replace. Regression test asserts it |
| Reporter reads a torn conversation file | MEDIUM | Tolerant parse, per-section degradation (tested). Separately: `save_conversation_to_disk` is non-atomic (`agent/persistence.py:92`) — worth its own small fix |
| Alerting becomes noise and gets muted | MEDIUM | State-change-only alerting with episode dedupe and a 1 h re-alert floor (§2.4) |
| Feed parse slows the report | LOW | mtime-keyed cache; `--no-feed` escape hatch. (Post-UIRESP2 the feed is ~4 MB, not 15.5 MB — this risk has materially shrunk) |
| GApplication forwarding unreachable from some launch contexts (SSH, systemd) | MEDIUM | Documented; Phase 4 exists as the fallback |
| Nudge races a turn completing at the same instant | LOW | `get_turn_state` check narrows it; residual documented. The message is either delivered to an idle session or refused |
| Report leaks project content or credentials | LOW | 120-char cap on message bodies by default; `--full` raises **message bodies only**; tool arguments and command outputs never rendered at any level (§2.1) |

---

## 9. Out of scope / follow-on

- **Auto-answering exec approvals** — permanently out, at any phase. The highest-risk capability in the system; would need its own spec and threat model. Reinforced as G1.
- **Auto-resume of `blocked_on_sendback`** — deliberately deferred. It requires a judgement about *which* agent should act and what the rejection meant; that is a PM decision, not a detection problem.
- **Remote/network access** to the app — explicitly out of scope; the whole point is no listener.
- **Non-atomic conversation persistence** (`agent/persistence.py:92`) — flagged here, belongs in a separate small fix.
- **Phase 4 file inbox** — fallback only (§5).

---

## 10. Effort

| Phase | Work | Effort |
|---|---|---|
| 1 | `utils/status_report.py` + `scripts/crab_status.py` + tests | 3–4 h |
| 1b | Cron wiring + episode dedupe state (§2.4) | 1 h |
| 2 | `main.py` flags + handler + guardrails + tests | 2–3 h |
| 3 | Auto-resume: episode identity, guardrail gate, state file, templates, tests | 4–6 h |
| 4 | File-inbox fallback (only if needed) | 2 h |

Sequencing: Phase 1 (+1b) ships first and delivers standalone value — the PM can read status and get stall alerts before any capability grant is approved. Phase 2 is a capability grant and requires the §12 sign-off on its own. Phase 3 depends on Phase 2's transport and on a period of Phase 1/2 operation producing real episode data.

---

## 11. PM decisions (recorded 2026-09-11)

| # | Question | **Decision** |
|---|---|---|
| 1 | **Nudge reach** — Supervisor only, or any agent? | **Supervisor only.** Codified in §3.2 and as a guardrail (§3.3) and invariant (§3.4.6) |
| 2 | **Stall alerting** — wire `--json` into cron? | **Yes.** §2.4. State-change-only with per-episode dedupe |
| 3 | **`--full` content** — full message bodies, or permanent 120-char truncation? | **Scoped `--full`.** 120-char default; `--full` raises **message bodies only** (2,000 chars). Tool arguments and command outputs are **never** rendered at any level (§2.1). PM may override |
| 4 | **Auto-resume** — confirm it stays out of scope? | **REVERSED — auto-resume is IN SCOPE.** Specified as Phase 3 (§4) with the guardrails in §4.3, disabled by default. `blocked_on_sendback` remains out (§9) |

---

## 12. Sign-off

- [ ] PM approves Phase 1 (status) for implementation
- [ ] PM approves the cron alerting in §2.4
- [ ] PM approves Phase 2 (nudge, Supervisor-only) **including the guardrails in §3.3** — this is a capability grant, not a utility
- [ ] PM approves Phase 3 (auto-resume) **including every guardrail in §4.3, in particular the G1 approval veto and the G10 kill switch** — this is an autonomous-action grant and the highest-risk item in the system
- [ ] Spec goes through the normal Coder → Debugger audit loop before any phase ships

**Note on sequencing:** Phase 1 and §2.4 are safe to approve and ship independently. Phase 3 should not be approved at the same time as Phase 2 — it depends on Phase 2's transport being proven in live use, and it should be reviewed with fresh eyes once real episode data exists.
