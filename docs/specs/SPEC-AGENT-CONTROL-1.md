# SPEC: Agent Control — Status Report + Nudge Channel

**Date:** 2026-09-11
**Author:** Supervisor (per PM direction following the 2026-09-11 stalled-pipeline investigation)
**Status:** Draft — for PM review before implementation
**Depends on:** none (Phase 1 is additive and standalone). Phase 2 depends on Phase 1's reporter module.
**Related:** `docs/specs/SPEC-UI-RESPONSIVENESS-2.md`, `docs/proposals/PROPOSAL-post-responsiveness-priorities.md`
**Target branch:** main (base `a3c95c2`)

> **Architecture compliance:** Phase 1 adds `utils/status_report.py` — pure Python, no GTK, no imports from `ui/`, read-only against existing files. The CLI shim `scripts/crab_status.py` follows the existing `scripts/rebuild_kb_index.py` precedent. Phase 2 touches only `main.py` (GApplication wiring) and routes into the existing `AgentRuntimeHandler.send_to_special_agent` (`ui/handlers/agent_runtime_handler.py:760`) — no new handler, no new layer, no handler-to-handler import. **No new listening socket, no new daemon, no client that reconnects.** Both phases work with the app closed (Phase 1) or open (Phase 2).

---

## DISCOVERY (Rule 1 — read before writing)

- Read `main.py` (57 lines): `CrabcakesApp(Gtk.Application)` is constructed at `:36` as `super().__init__(application_id='com.crabcakes.app')` — **no `flags=`**, and no `command-line` / `handle-local-options` handler. Under current behaviour a second invocation simply activates (focuses) the running instance.
- Verified the app **already owns `com.crabcakes.app` on the session bus** (`gdbus … ListNames` → `'com.crabcakes.app'`). GTK's GApplication single-instance + command-line forwarding is therefore already available; it is unused, not missing.
- `gdbus introspect --session --dest com.crabcakes.app --object-path /` returns only an empty `com` node — there is **no D-Bus control interface** today, and no action map.
- Read `ui/handlers/agent_runtime_handler.py`: `send_to_special_agent(self, session_key: str, text: str) -> None` at `:760` is the single entry point the chat box uses to start an agent turn. It performs the pre-loop preparation and calls `rt.send_message`. This is the correct target for a nudge — routing anywhere else would bypass turn tokens and the `_ended_sessions` discipline.
- Read `agent/persistence.py`: conversations persist to `<config>/conversations/<session_key>.json` (`conversations_dir()` `:28`). Session keys are `special:supervisor`, `special:coder`, `special:debugger` (observed on disk). **`save_conversation_to_disk` writes non-atomically** — `open(path, "w")` then `json.dump` at `:92-93` — so a concurrent reader can observe a truncated file. Any reader must tolerate `json.JSONDecodeError` (and it is worth noting separately: a crash mid-write loses that conversation's tail).
- Read `utils/feed_store.py`: the feed snapshot is written via `_atomic_write_json` (`.tmp` + `os.replace`), so **reads are consistent without taking the flock**. A status reader must NOT acquire the feed lock — `_acquire_lock` is a bounded-but-still-blocking flock and the app holds it during compaction.
- Read `agent/runtime.py`: `TurnStatus` enum (`:120`) with `RUNNING`/`STREAMING` non-terminal and `COMPLETED`/`FAILED`/`CANCELLED` terminal; accessors `get_turn_state(session_key)` (`:1942`) and `get_last_turn_result` (`:1917`) exist and are exactly what Phase 2's refuse-when-busy guardrail needs.
- Verified observability sources already on disk (used by hand during the 2026-09-11 investigation): `~/.config/crabcakes/conversations/*.json`, `~/.config/crabcakes/audit-log.jsonl` (4,064 entries; `{tool_name, args_hash, approved, timestamp}`), `.crabcakes/feed.json` (10,170 cards, 15.5 MB), `.crabcakes/tasks.md`, `/var/crash/*.crash` (apport; carries `Signal`, `ProcCmdline`, `Date`, `ProcMaps`).
- Verified **no** existing path for either capability: no agent-control API (the only listener is the KB server `kb_server.py:248` — `/health`, `/agents`, `/v1/chat/completions`), no CLI subcommands, no D-Bus actions, no filesystem inbox, and no Wayland input tooling installed (`xdotool`/`ydotool`/`wtype`/`dotool` all absent).
- Architecture owner: `main.py` owns GApplication lifecycle; `ui/handlers/agent_runtime_handler.py` owns turn submission; `utils/` owns pure read-only helpers.

---

## 1. Overview

### 1.1 Problem

The agent pipeline can stall in ways that are invisible from outside the app. On 2026-09-11 the Coder's turn ended silently — last message *"Confirmed the bug. Writing the **red tests first**."*, no tool call following — and the pipeline sat idle for 3.5 hours. Diagnosing it required reading the process table, three conversation JSON files, the 15 MB feed, the audit log, git state, and `/var/crash` **by hand**.

There is no supported way to (a) ask the app what it is doing, or (b) deliver a message to an agent without a human at the keyboard and a mouse on the right tab.

### 1.2 Solution

Two capabilities, both built on things that already exist:

- **Phase 1 — `crabcakes-status`:** a read-only reporter over the files the app already writes. Works whether the app is running or closed, headless, no GTK. Detects the specific stall classes (turn ended without a tool call, blocked on a sendback, main thread pinned).
- **Phase 2 — `--nudge`:** a command-line entry that forwards a message to a specific agent through GTK's built-in GApplication single-instance channel (the session bus the app already joins) and into the existing `send_to_special_agent`. No socket we own, no daemon, no reconnect loop.

### 1.3 Scope

| In | Out |
|---|---|
| `utils/status_report.py` — pure collector/renderer | Any new network listener or HTTP API |
| `scripts/crab_status.py` — CLI shim (`--json`, `--no-content`, `--project`) | Modifying `agent/runtime.py` turn semantics |
| `main.py` — `HANDLES_COMMAND_LINE`, `--nudge`, `--status` | Remote/over-network control of the app |
| Guardrail + audit-trail plumbing for nudges | Auto-answering approvals, auto-resuming stalled turns (PM decision, §11) |
| Tests for both phases (headless) | Phase 3 file-inbox (fallback only, §4) |

### 1.4 Principles

- Read-only by default; the reporter never mutates app state and never takes the feed flock.
- No new listening socket, no daemon, no long-lived client.
- Same-user, session-scoped only — the same trust boundary as `systemctl`.
- Every mutation of agent state must be **visible**: a nudge appears in the feed and the audit log, with its origin.
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

1. **`turn_stalled`** — for any session: last message role is `assistant`, no tool result follows it, `now - file_mtime > threshold` (default 10 min), and **no repo writes since that message.** This is precisely the 2026-09-11 failure.
2. **`blocked_on_sendback`** — a `*SENDBACK*.md` exists in `docs/specs/` newer than the newest commit, and no commit has touched the locked files since. Means "an audit rejected work and nobody has picked it up".
3. **`app_spinning`** — main thread `busy` per the table above (the pre-fix freeze signature).
4. **`approvals_pending`** — ≥3 approval entries in the last 30 min with no file writes after them.
5. **`crash_after_start`** — a crash report whose `Date` is after the running app's start time.

**Read-safety requirements (must be tested):**

- Tolerate `json.JSONDecodeError` on any conversation file — `save_conversation_to_disk` is non-atomic (`agent/persistence.py:92`). On parse failure, report the file as `unreadable (writer active)` and continue.
- Never call `feed_store._acquire_lock`. Feed reads are safe because writes are atomic (`os.replace`).
- Truncate message content to 120 chars by default; `--full` opts in. Conversation files contain project content; the report is not a place for it.
- Cache the parsed feed summary in `<cache>/crabcakes/status-feed.json` keyed by `(path, size, mtime)` — `feed.json` is 15.5 MB and full parse costs ~0.3 s. Target: **whole report < 1 s**.

### 2.2 `scripts/crab_status.py` (new)

Thin CLI over the module:

```
crab_status.py [--project PATH] [--json] [--full] [--no-feed] [--watch N]
```

- Default: human-readable report (the format demonstrated in §1 of the 2026-09-11 investigation write-up).
- `--json`: machine-readable, for cron/alerting.
- Exit codes: `0` healthy, `2` attention needed (any stall class fired), `3` app not running (report still emitted for the filesystem side).

### 2.3 Invariants

1. Phase 1 changes nothing the app writes and never imports GTK.
2. Report generation is correct with the app **closed**.
3. No lock is ever taken on `feed.json`; a report cannot block or be blocked by the app.
4. A truncated/unreadable input degrades one section, never the whole report.
5. `assess()` returns `2` for the exact 2026-09-11 shape (assistant-final message, no tool call, no writes, > threshold).

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
        # --nudge @Agent "text" → validate, then deliver to the running instance
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
- Agent → session key: `@Supervisor` → `special:supervisor` (lowercase). Validate against the known agent set (`prompts/default_agents/*.yaml`: coder, debugger, supervisor, auxilium). Unknown agent → exit `3`.
- Delivery: build the concrete `AgentRuntimeHandler` for that session and call `send_to_special_agent(session_key, text)` — the same path the chat box uses, so turn tokens, `_ended_sessions`, and the pre-loop preparation all behave identically.

### 3.3 Guardrails (required, not optional)

| Guardrail | Behaviour |
|---|---|
| Payload cap | 4,096 chars (matches the `/ask` cap in `project-awareness.md`) → exit `5` |
| Turn in flight | Refuse if `rt.get_turn_state(sk)` is `RUNNING`/`STREAMING` (`agent/runtime.py:1942`, `:120`) → exit `2`, message `turn in flight for <agent>; retry when idle` |
| Session must exist | Refuse if the conversation is not already loaded/persisted → exit `6`; require an explicit `--create` to make one |
| Same user only | Inherent: the session bus is per-user. Document it; do not add a bypass |
| **Audit trail** | Every nudge writes (a) a feed card showing the text and target, and (b) an `audit-log.jsonl` record `{origin: "cli-nudge", target, chars, text_sha256[:16], timestamp}` — the hash, not the raw payload |
| **Visibly distinct from PM input** | The injected feed card carries `metadata["origin"] = "cli-nudge"` and renders a visible origin marker (e.g. `via CLI`). A nudge must NEVER be indistinguishable from a message the PM typed — the PM has to be able to tell, at a glance in the feed, which turns they authored and which arrived through this channel |
| Visible in the UI | The injected message renders in the target tab exactly as a typed message does, apart from the origin marker above |

Exit codes: `0` delivered · `2` refused (turn in flight) · `3` unknown agent · `4` app not running · `5` payload too long · `6` no such session.

### 3.4 Invariants

1. No new listening socket, port, or daemon is created by either phase.
2. A nudge is never delivered silently — feed card + audit record always accompany it.
3. A nudge cannot interleave with a running turn.
4. `--nudge` with the app closed never starts a GUI.
5. Phase 2 cannot be reached by anything but a same-user local process.

---

## 4. Phase 3 — fallback only (file inbox)

**Not in scope unless Phase 2's bus routing proves unreliable** (e.g. the app is launched from a context that is not on the user's session bus — SSH, systemd unit).

Design if needed: the app polls `.crabcakes/inbox/` on a 1 Hz GLib timer (reusing the activity ticker's pattern, `ui/handlers/activity_handler.py:641`), reads `*.json` payloads `{target, text, ts, id}`, applies the same guardrails, then moves each to `.crabcakes/inbox/done/`. Requires: adding a timer, adding `.crabcakes/inbox/**` to `_should_ignore` in `crabwatch_handler.py:47` so the watcher does not emit feed cards for the channel's own traffic, and a per-message id for idempotency. Costs more code and introduces polling; prefer Phase 2.

---

## 5. Data flow

```
Phase 1 (read-only, app may be closed)
  /proc/<pid>  ─┐
  conversations ─┤
  feed.json     ─┼─→ utils/status_report.collect() → render_text|render_json → exit code
  audit-log     ─┤
  git, /var/crash ┘

Phase 2 (app running)
  crab_status nudge ─→ main.py --nudge @Supervisor "…"       [second process, exits]
        └─ GApplication forwarding (session bus, already joined)
              └─ running instance: on_command_line
                    ├─ validate (agent, cap, session, turn state)
                    ├─ feed card (source=user) + audit record (hash)
                    └─ AgentRuntimeHandler.send_to_special_agent(sk, text)
                          └─ rt.send_message → _run_loop (background thread)
```

---

## 6. Test plan

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
| `test_content_truncated_by_default` | 1 | 120-char cap; `--full` opts in |
| `test_argv_parse_nudge_forms` | 2 | `--nudge @Supervisor "x"`, quoting, missing agent, oversized payload |
| `test_nudge_refused_when_turn_in_flight` | 2 | With a fake runtime returning `STREAMING` → exit `2`, no dispatch |
| `test_nudge_logs_feed_card_and_audit_record` | 2 | Both artefacts written; audit record carries the hash, not the text |
| `test_nudge_card_is_marked_as_cli_origin` | 2 | Feed card carries `metadata["origin"] == "cli-nudge"` and renders the origin marker; a typed message does not |
| `test_nudge_does_not_start_gui_when_not_remote` | 2 | `get_is_remote()` False → exit `4`, no `present()` |

Manual integration (documented, run once per phase): start the app → `main.py --nudge @Supervisor "ping"` → confirm the message appears in the Supervisor tab and both log artefacts exist.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Capability escalation** — a nudge is an instruction into an agent with file-write and exec access | HIGH | Same-user/session-only; 4,096-char cap; refuse-when-busy; mandatory feed card + audit record; PM sign-off required before Phase 2 ships |
| Reporter blocks on the feed lock | MEDIUM | Reporter never locks; reads rely on atomic replace. Regression test asserts it |
| Reporter reads a torn conversation file | MEDIUM | Tolerant parse, per-section degradation (tested). Separately: `save_conversation_to_disk` is non-atomic (`agent/persistence.py:92`) — worth its own small fix |
| 15.5 MB feed parse slows the report | LOW | mtime-keyed cache; `--no-feed` escape hatch |
| GApplication forwarding unreachable from some launch contexts (SSH, systemd) | MEDIUM | Documented; Phase 3 exists as the fallback |
| Nudge races a turn completing at the same instant | LOW | `get_turn_state` check narrows it; residual documented. The message is either delivered to an idle session or refused |
| Report leaks project content | LOW | 120-char truncation by default; `--full` explicit |

---

## 8. Success criteria

- [ ] `crab_status.py` produces a correct report in <1 s, with the app both running and closed
- [ ] It detects the 2026-09-11 stall shape (`turn_stalled`) and the `blocked_on_sendback` shape, each with a named agent/unit
- [ ] Exit codes usable from cron (`0`/`2`/`3`)
- [ ] `--nudge` delivers a message that appears in the target tab and leaves both log artefacts
- [ ] `--nudge` refuses (exit `2`) when a turn is in flight, and never starts a GUI when the app is closed
- [ ] **No new listening socket, no daemon, no reconnecting client** — verified by `ss -tlnp` before/after
- [ ] Phase 1 tests pass headless with no GTK in the import path
- [ ] Full-suite failure set unchanged against the recorded baseline (the AC3 discipline)

---

## 9. Out of scope / follow-on

- **Auto-resume of stalled turns** — deliberately not included. Detecting the stall is Phase 1; *acting* on it automatically is a PM decision (§11), not a default.
- **Remote/network access** to the app — explicitly out of scope; the whole point is no listener.
- **Auto-answering exec approvals** from the CLI — the highest-risk capability in the system; would need its own spec and threat model.
- **Non-atomic conversation persistence** (`agent/persistence.py:92`) — flagged here, belongs in a separate small fix.
- **Phase 3 file inbox** — fallback only (§4).

---

## 10. Effort

| Phase | Work | Effort |
|---|---|---|
| 1 | `utils/status_report.py` + `scripts/crab_status.py` + tests | 3–4 h |
| 2 | `main.py` flags + handler + guardrails + tests | 2–3 h |
| 3 | File-inbox fallback (only if needed) | 2 h |

---

## 11. Open questions for the PM

1. **Reach:** should `--nudge` be allowed to target Coder and Debugger directly, or Supervisor only? (Recommendation: any known agent, since the Supervisor is itself just an agent — but every nudge is logged regardless.)
2. **Stall alerting:** should `crab_status.py --json` be wired into cron so a stalled pipeline pings you instead of waiting to be noticed? (Optional; the exit codes are designed for it.)
3. **`--full` content:** should the report ever include full message bodies, or is 120-char truncation permanently right?
4. **Auto-resume:** explicitly deferred. Confirm it stays out of this unit.

---

## 12. Sign-off

- [ ] PM approves Phase 1 (status) for implementation
- [ ] PM approves Phase 2 (nudge) **including the guardrails in §3.3** — this is a capability grant, not a utility
- [ ] Spec goes through the normal Coder → Debugger audit loop before either phase ships
