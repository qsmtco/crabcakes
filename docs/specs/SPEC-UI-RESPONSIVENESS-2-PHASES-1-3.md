# SPEC: UI Responsiveness 2 — Implementation of Phases 1–3 (Feed Write Path)

**Date:** 2026-09-11 (rev 4 — Debugger spec-audit rounds 1–3 folded in)
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/specs/SPEC-UI-RESPONSIVENESS-2.md` §2.1 (Phase 1), §2.2 (Phase 2), §2.3 (Phase 3) only. Phases 4–8 of the parent spec are **out of scope** for this loop.
**Depends on:** SPEC-AUDIT-CLEANUP-3 (landed: delta coalescing, 500 ms throttle, single ticker); SPEC-UI-RESPONSIVENESS Phase 1 (landed: defer_prompt_build)
**Target branch:** main
**Baseline at authoring:** 352caf7

> **Architecture compliance.** `utils/` stays pure Python file I/O (no GTK; the one new piece of module state — the compact rate-limit dict — is documented below and guarded by a module lock). All threading lives in the handler layer. No new imports from `ui/` into `utils/`. GTK-touching tests run under `xvfb-run -a`. Full-suite failure set must remain byte-identical to baseline (the AC3 discipline).

---

## Spec audit log

- **Round 1 (16 BUGs):** 10 folded, 6 overridden with source verification (all 4 override rationales **confirmed correct by the auditor in round 2**).
- **Round 2 (14 flagged):** all 14 dispositions verified present; fold-ins introduced new hazards → rev 3.
- **Round 3 (17 flagged; 4 CRITICAL):** auditor verified all 3 supervisor source facts (add_card seq RMW :713-716 unlocked; build_feed_card constructs GTK; _load_and_render background-only). Root cause of every round-2/3 regression class: fold-in machinery added without end-to-end trace. **Rev 4 responds by simplifying, not adding**: 12 folded, 5 accepted/documented, rest auditor-self-resolved.
  - **#1 tri-state-loss** → `update_feed_card`: journal-append success ⇒ **True regardless of compaction outcome** — the threshold compact is wrapped in its own try/except (failure logged WARNING, retried naturally by the next threshold crossing; the journal line is already durable, so re-deferral is wrong and duplicate-line growth is impossible). False only when append failed AND legacy failed.
  - **#2 fresh-wins fiction** → a fresh enqueue **discards** any deferred entry for the same key (`_persist_deferred.pop(key)` under the lock): new payload, fresh retry budget. "Fresh wins" is now structural, not advisory.
  - **#3 snapshot-timing race + #7 captured-reference staleness** → `_ui` deep-copies the card on the main thread before starting the persist thread; the persist thread writes the copy — a consistent point-in-time state. (System cards never carry snapshots — no file_path ⇒ `_maybe_create_snapshot` no-ops — so the copy is a guaranteed non-issue, not a race-window fix.)
  - **#4 wakeup-during-stop + #19 wait-before-stop-check** → loop restructured: stop-check at top; during stop, failures **drop with ERROR instead of deferring**; retry wakeup gated on `not self._persist_stop`; `_requeue_deferred` drops remaining deferred at shutdown with ERROR. Shutdown is bounded: at most one final drain pass.
  - **#5 high-rate I/O thrash** → `_maybe_compact` rate-limited: at most one append-triggered compact per project per 60 s (module-level dict + lock in feed_store, documented deviation from the pure-functions docstring).
  - **#9 load-time compact no retry** → compact failures re-enqueue (cap 3, then ERROR) — same retry budget as updates.
  - **#10 type-trust** → metadata validated dict at BOTH enqueue (drop the key + WARNING) and journal write (skip + WARNING + False → legacy fallback).
  - **#12 timeout vs feed size** → `load_feed` lock timeout scales with file size: `min(60.0, 10.0 + size_bytes / 1_000_000)` seconds (≥10 MB/s patience vs a ~5 MB/s compact).
  - **#15 unsound main-thread test** → the new tests use a **recording GLib fake** (queue-only, manual `fire()`); the existing sync `MockGLib` is untouched. Plus an AST structural test: `_surface_prune_card`'s `add_card` call site must sit inside a nested function (never the method body).
  - **#16 parse duplication** → extract `_parse_cards(raw)` and `_apply_overlay(cards, overlay)`; `load_feed` and `compact_feed` both use them.
  - **#17 hardcoded window in body** → `window` passed to `_surface_prune_card`.
  - **#18 inherited retry counter** → new writer generation resets deferred `tries` to 0 (payloads kept) — logged INFO. Bounded in practice: each reset requires a close/reopen cycle.
  - **#25 doc-lie "single writer thread"** → §7 wording fixed (multiple append threads; the flock serializes).
  - **#8 gitignore race — accepted, documented:** `_ensure_gitignore_entry`'s read-modify-write is not flock-protected. **Pre-existing** (every `save_feed`/`append_feed_card` call today has the same exposure); inherited, not introduced; low real-world risk (same-process callers rarely race; concurrent processes rare). Flagged for post-mortem §8; NOT fixed here (per-project gitignore locking = scope creep).
  - **#20 (unsynchronized-but-atomic read, guard-mitigated), #23/#24/#26 — auditor no-bug conclusions. #11/#21 (wasted concurrent compaction) — accepted: flock-serialized no-op folds, bounded by the #5 rate limit.**
- **Round 4 (15 flagged; 4 CRITICAL):** convergence — the round-4 findings are semantics refinements, not structural holes. 6 folded, 5 accepted/documented, rest auditor-self-resolved:
  - **r4#1/#4 (in-pass compact retry spin)** → compact retries move to the **next pass**: a failing compact is appended to `_persist_compactions` with `tries+1` **only if it isn't the head at loop start** — implemented via a one-pass-local `retried_this_pass: set[str]`; while a path is in that set, the drain skips it (picks the next task instead) and the set is cleared at pass start. ≤1 compact attempt per path per pass; pass duration bounded by the tasks present at pass start.
  - **r4#2 (counter inheritance)** → the deferred store becomes per-payload: the drain's failure-write always records `(task[1], 1)` **when no deferred entry exists for the key**, else increments — AND the enqueue's deferred-discard is complemented by a **generation token**: `_persist_deferred[key] = (payload, tries, enqueue_gen)`; a new enqueue bumps the key's generation, and a failure-write only increments when its payload's generation matches the deferred entry's. Simplest correct form (chosen): **the failure-write sets `tries=1` if the queued payload differs from the deferred payload** (identity compare on the payload dict), else increments. Fresh payload ⇒ fresh budget, structurally.
  - **r4#3 (join vs compact duration)** → `shutdown_persist_writer`'s join timeout **scales**: `min(60.0, 5.0 + feed_size_mb)` where feed size is read (best-effort, `os.path.getsize` on the project's feed path — worst-case default 5 s) at shutdown time. The "leftover" log becomes two honest branches: (a) join timed out AND queue non-empty → "N undrained entries"; (b) join timed out AND queue empty → "writer still draining at join timeout; entries were drained but exit was not observed".
  - **r4#9 (reset bound mis-documented)** → wording fixed: the tries-reset happens **per new writer thread start** (any exit: stop, crash), not per close/reopen. Bounded in practice: each reset requires the old writer to have exited.
  - **r4#10 (dedup conflates external/internal)** → external `_enqueue_compaction` **replaces** any existing entry for the same path (fresh `tries=0` — a load-time trigger is a new attempt): search for the path, replace-or-append. Internal retry re-enqueue (the failure path) appends only if absent **and** records the incremented tries. The two paths no longer share a dedup rule.
  - **r4#14/#18 (legacy False conflation)** → `_update_feed_card_legacy` returns a **tri-state**: `True` (written), `False` (write failure: lock timeout / OSError), `None` (card not found). `update_feed_card` maps: append-ok → True; append-fail → legacy tri-state passthrough (True/False/None). The writer treats only `False` as failure-and-defer; `None` (card gone) is logged INFO and **dropped without deferral** (retrying a gone card is futile). `test_update_nonexistent_returns_false` rewritten to assert `is None` for the legacy-path nonexistent case; journal-path nonexistent still True (D4).
  - **r4#19 (compact-feed-records-timestamp not in snippet)** → `compact_feed` body explicitly records `with _compact_rl_lock: _compact_last[project_path] = time.monotonic()` after a successful fold; shown in the snippet.
  - **r4#5 (rate-limit semantics), #11 (timeout vs dynamic size), #12 (module state), #16 (AST lambda caveat), #17 (unbounded dict) — accepted/documented:** #5/#12/#17: rate-limit state is per-project-keyed, process-global by design, tiny (~100 B/project), no eviction — documented in §2.2.1; cross-handler same-project interference is a corner case with no production instance (one FeedHandler per process — grep-verified single instantiation in window.py). #11: the size-vs-timeout estimate is approximate by design (getsize precedes acquire; a shrink over-estimates patience, a growth under-estimates; the ≥10 s floor dominates for typical feeds). #16: the AST test documents the `def`-not-lambda constraint for `_ui` and the test fails on refactor to lambda — intentional enforcement.
  - r4#6/#8/#13/#15/#20/#22/#23/#24/#25 — auditor no-bug-after-trace or future-hazard-accepted (#15: system cards never carry snapshots — verified; if that ever changes, the deepcopy cost note applies).
- **Round 5 (5 flagged: 4 CRITICAL + 1 HIGH):** the highest-quality round — caught a build-time crash (missing `import os`) and a genuine infinite-retry design flaw. All 5 folded + 4 mediums:
  - **r5#1 (missing `import os`)** → import added to §2.1.1 (module imports currently lack `os` — verified).
  - **r5#2/#3/#19 (re-merge discards tries / identity compare too strict)** → **structural fix: deferred entries are attempted IN PLACE** — `_requeue_deferred` is DELETED; the drain attempts deferred entries directly (payload stays in the deferred map across passes; increment-on-failure is direct; no move to the queue, no clear-and-re-add, no payload comparison at all). Fresh-enqueue-fresh-budget holds by construction: enqueue pops any deferred entry for the key, so deferred and queue entries for one key are mutually exclusive. Success removes OUR entry only (identity-guarded against a newer failure having replaced it).
  - **r5#18 (external enqueue violates pass bound)** → compactions are **snapshotted at pass start** (`list(...)` + `clear()` under the lock); entries added during the pass — internal retries or external triggers — are processed next pass. ≤1 attempt per path per pass regardless of source.
  - **r5#4 (log conflates undrained vs straggler)** → `queued_at_stop` snapshot before the join; three-way exit logging (straggler WARNING / undrained ERROR / exit-not-observed WARNING).
  - **r5#15 (unbound task/kind)** → `kind`/`task` initialized to None before the try in the queue phase (and the restructure eliminates the mixed-task loop entirely — separate phases with fixed task shapes).
  - **r5#13 (docstring)** → `_ensure_persist_writer` docstring now says per-new-thread-start.
  - **r5#16 (fragile dict iteration)** → `list(self._project_paths.values())` snapshot.
  - r5#5–#12, #14, #17, #20–#24 — auditor no-bug-after-trace; arithmetic fuzziness in the audit log's bundling noted, dispositions complete.
- **Round 6 (exit round — ACCEPTED, 0 CRITICAL/HIGH):** 3 MEDIUM/LOW findings carried as **build-time notes for the Coder**:
  1. *(r6#5, MEDIUM — accepted)* The shutdown three-way log can conflate stragglers with undrained originals when some originals were drained AND stragglers arrived (the undrained-ERROR then covers both). Acceptable pragmatism; the Coder adds a test pinning the accepted behavior.
  2. *(r6#15, MEDIUM — accepted)* An external `_enqueue_compaction` resets the compact retry budget (per-path cap, not per-failure) — a misbehaving caller could keep a compact budget alive. Accepted per the "external trigger = new attempt" semantic; documented.
  3. *(r6#1, LOW — fixed in this rev)* Narrative said "no payload comparison at all" — corrected: **no payload comparison in normal operation**; the deferred phase's success/failure branches carry a defensive identity-guard (`cur[0] is payload`) that mutual exclusivity makes unreachable, present only to keep the map consistent if the invariant is ever broken.

---

## DISCOVERY (verified against source at 352caf7)

- Read `utils/feed_store.py` (431 lines): `_atomic_write_json` (:30, `indent=2` hardcoded :38, chmod 0o600, os.replace); `_acquire_lock` (:96-113, 5 non-blocking retries then **unbounded blocking** `fcntl.flock(fd, LOCK_EX)` at :112); `load_feed` (:124); `save_feed` (:169, lock-free, **no production callers** — tests only); `append_feed_card` (:190, lock→json.load→parse all→append→write all); `update_feed_card` (:227, lock→load all→setattr one card (allowed set `{"accepted","reviewed","metadata"}` :258)→write all); prefs functions (:310+, use `_atomic_write_json` at :429 — small files, keep `indent=2`).
- Read `ui/handlers/feed_handler.py` (1897 lines): `__init__` state block (:60-90: `_cards`, `_card_widgets`, `_project_cards`, `_project_paths`, `_project_seq`, `_lock = threading.Lock()` :82, `_backlog` :87, `PAGE_SIZE = 15` :89); `add_card` (:700 — `card_id` uuid4; **`_project_seq[proj] += 1` at :713-716 NOT under the lock**; deferred `_finalize_snapshot` via `idle_add` :727; `_cards`/`_project_cards` stored under `self._lock` :730-737; **`build_feed_card` constructs GTK widgets :741-761**; persist via per-card daemon thread :806-812 calling `append_feed_card`); `update_card` (:963 — early-return if `card_id not in self._cards` :974; sync persist via local `from utils.feed_store import update_feed_card` at :1016-1021 with payload `{"body", "metadata"}`); `add_cards_batch` (:817) persists via `_persist_all` (:925-937, `append_feed_card` — verified); accept path sync persist (:1431 `{"accepted": True}`); reject path sync persist (:1492 `{"accepted": False}`); `_load_and_render` inner fn of `on_project_opened`, runs on a **background daemon thread** (:1224), loads via `feed_store.load_feed` (:1103), sets `_loading=True` (:1100), migrates `seq_num=None` cards (:1124-1134), rebuilds `_project_seq` from `max(card.seq_num)` (:1137); seq assignment at card creation (:722, :856); `clear_project` (:1059) pops state under `self._lock`; `on_project_closed` (:1227) → `clear_project` + empty-state dispatch.
- Read `ui/handlers/agent_runtime_handler.py`: `_do_tool_call_result` (:1300, main thread via `GLib.idle_add` :1294) mutates card then calls `self._fh.update_card(card_id, card)` (:1345); approval path calls it (:671). Both confirmed the main-thread sync-persist callers.
- Read `ui/window.py`: project-close lambda chain (:585-592) calls `feed_handler.on_project_closed(name)`, `crabwatch_handler.stop_watching()`, etc. — the wiring point for Phase 1 project-close shutdown. `MainWindow.__init__` connects `"realize"` (:66); **no `close-request` handler exists anywhere** (grep-verified) — app quit currently goes straight to process exit.
- Read `main.py`: `Gtk.Application` with `activate` only; no shutdown/close-request wiring.
- Read `models/feed_card.py`: `FeedCardData` fields incl. `body: str`, `metadata: dict`, `reviewed: bool = False`, `accepted: bool | None`, `seq_num: int | None`, `conversation_snapshot: ConversationSnapshot | None` (:65 — the snapshot lives on its **own field**, serialized into the output dict only inside `to_dict` via `_serialize_metadata_with_snapshot` :127-131; the live in-memory `metadata` dict does not hold the snapshot object); `CardType` Literal (11 values incl. `git_commit`); `to_dict`/`from_dict` round-trip all fields.
- Read `tests/test_feed_store.py` (13 tests): round-trip, append, update (`test_update_existing_card_accepted` :115, **`test_update_nonexistent_returns_false` :126**, `test_update_reviewed_flag` :130), malformed JSON/card handling. Read `tests/test_low12_13_feed.py`: exercises `_atomic_write_json` permissions/gitignore helpers (behavior assertions, no `indent`-format assertions — verified). Read `tests/test_feed_handler.py` (:3616 lines): **`MockGLib.idle_add` runs callbacks synchronously on the calling thread** (:19 — verified by the auditor); approval test patches `ui.handlers.feed_handler.feed_store` wholesale (:570); unknown-card-id warning test (:3591-3611).
- Live measurements (parent spec §DISCOVERY + §0, py-spy 2026-09-11): `update_feed_card` = 0.62 s on the real 13.9 MB / 9,500-card feed; main thread sampled 27/39 non-idle samples in this path; **`append_feed_card` json.load is the single hottest flamegraph frame (8.58 %)**; main thread parked in the unbounded lock fallback 9×.

### Deviations from the parent spec (deliberate, each justified in place)

| # | Parent says | This spec does | Why |
|---|---|---|---|
| D1 | §2.3 `feed-meta.json` `seq_floor` for seq continuity | **No new file.** Rely on the existing `_load_and_render` rebuild (`max(card.seq_num)`, feed_handler.py:1137) | The window keeps the *newest* N cards; seq assignment is monotonic (incremented per card at :722/:856, counter rebuilt from max at load), so the max-seq card always survives pruning unless the feed is under the window (in which case no pruning happens). Test `test_seq_num_monotonic_across_compaction` proves the invariant. |
| D2 | §2.2 journal records carry only `updates` | Same — journal carries updates only. Appends stay snapshot-side (`add_card`'s `_persist` :806-812 and `add_cards_batch`'s `_persist_all` :925-937 both call `append_feed_card` — verified) | Preserves `test_append_*` semantics exactly; stays in scope. Post-Phase-3 the snapshot is bounded at `FEED_WINDOW_DEFAULT` cards, so append's RMW cost is bounded (tens of ms on background threads — never the main thread). Routing appends through the journal would change `append_feed_card`'s observable semantics; deferred as an evolution item. |
| D3 | §2.2 allowed set `{"accepted","reviewed","metadata"}` | **Add `"body"`** (journal path, replay, legacy path) | Latent bug found in pre-flight: `update_card` persists `{"body", "metadata"}` (:1016-1021) but the store drops `body` — on-disk cards keep stale bodies after tool results. One-word change with a new test. No existing test asserts body is *not* persisted (verified). |
| D4 | §2.2 returns False when card not found | Journal path returns **True ("safely recorded")**. Legacy fallback returns a **tri-state** (True=written / False=write failure / None=card not found). Grep evidence: production callers (`update_card` :1020→enqueue, accept :1431, reject :1492) are fire-and-forget; the handler writer maps False→defer-retry, None→INFO-drop (retrying a pruned card is futile). One test rewritten (system-level + tri-state assertions) | "Not found" moves to replay/compact-time for the journal path; the legacy path distinguishes it from write failures via None. No caller branches on the old binary value in a way the tri-state breaks (grep-verified). |
| D5 | §2.1 writer loop `while not self._persist_stop` | **Stop-check-at-top loop; drain-before-exit with post-stop re-check; deferred-retry map with fresh-enqueue-discards-deferred semantics; failures during stop drop with ERROR** | Parent's loop exits with a non-empty queue; the naive fix had the round-1 race; the round-3 shape bounds shutdown (≤ one final drain pass) while never stranding stragglers. Daemon hard-exit durability window (≤ one in-flight write) accepted per parent §5 row 3. |
| D6 | §2.2 compaction triggers only from the update path | **Also** rate-limited threshold check in `append_feed_card` (≤1 compact/project/60 s; lock released first), **and** a one-time large-feed compaction on project open (writer-side, retried ≤3 on failure) | Append-only feeds would otherwise grow unbounded; the existing 13.9 MB feed would stay 13.9 MB until 500 journal lines accrue. Both triggers run on background threads. **Accepted latency (round-1 BUG #6):** first tool results after a legacy-feed open may wait behind the one-time compaction — one-time upgrade cost. |

---

## 1. Overview

### 1.1 Problem (from parent spec, verified)

Every tool result and approval triggers `feed_store.update_feed_card` synchronously on the GTK main thread: lock → `json.load` 9,500 cards → mutate one → `json.dump` all 9,500 at `indent=2`. Measured 0.62 s/call; 100 % of main-thread profiler samples; the lock fallback can block unbounded; the file grows forever.

### 1.2 Solution (three phases, one loop)

- **Phase 1 — background coalescing writer** (`feed_handler.py`, `window.py`): producers enqueue; one daemon writer thread drains with last-write-wins coalescing, a deferred-retry map (fresh-enqueue-discards-deferred), and a compaction list. Main-thread cost per tool result: ~620 ms → <5 ms (design target) / <50 ms (test bound).
- **Phase 2 — O(1) update journal + compaction + bounded lock** (`feed_store.py`): updates append one JSONL line under the flock; `load_feed` reads snapshot + journal under one lock hold (size-scaled timeout); compaction folds the journal when it exceeds 500 lines; `_acquire_lock` bounded (never blocks unbounded). **Uniform rule: every feed_store mutation (snapshot or journal) holds the feed flock.**
- **Phase 3 — sliding-window pruning** (`feed_store.py`, `feed_handler.py`): compaction retains the newest `FEED_WINDOW_DEFAULT = 2000` cards; actionable cards pinned; pruning logged + surfaced as a system card (UI on the main thread via idle_add, persistence from a copy); one-time large-feed compaction on project open.

### 1.3 Scope

| In | Out |
|---|---|
| `utils/feed_store.py` — journal, replay, compaction, pruning, bounded lock, compact serialization, `save_feed` lock, rate limit | Parent Phases 4–8 (deferred card render, git offload, lock sharding, render pool, spike) |
| `ui/handlers/feed_handler.py` — writer thread, enqueue call-sites, compaction queue, load-time trigger, prune surfacing, `add_card(persist=)` param | `FeedCardData` field set (unchanged) |
| `ui/window.py` — project-close + close-request shutdown wiring | `gateway/` (no feed persistence — grep-verified in parent) |
| `tests/test_feed_store.py`, `tests/test_feed_handler.py` | Routing `append_feed_card` through the journal (D2) |
| `docs/ARCHITECTURE.md` — feed persistence sections (targets found by grep, §8) | Any behavior change to job/turn state machines |

**Files NOT changed:** `models/feed_card.py`; `agent/runtime.py` (parent Phase 6); `ui/handlers/agent_runtime_handler.py` (its `_fh.update_card` call-sites are unchanged — Phase 1 changes the *inside* of `update_card`); `ui/handlers/crabwatch_handler.py`; `utils/git_ops.py` (parent Phase 5); `main.py` (window `close-request` suffices).

---

## 2. Changes by File

### 2.1 Phase 1 — `ui/handlers/feed_handler.py` + `ui/window.py`

**2.1.1 Instance state (in `__init__`, after `self._lock` at :82):**

```python
        # ── Background feed persistence (SPEC-UI-RESPONSIVENESS-2 Phase 1) ──
        # One writer thread per handler. Producers enqueue (project_path,
        # card_id, updates); the dict coalesces per (project, card). Failed
        # writes move to _persist_deferred (retry cap); a FRESH enqueue for
        # the same key discards the deferred entry (new payload, fresh
        # budget). Compactions ride a separate list (a sentinel in the
        # update keys would be unpacked as a path).
        self._persist_queue: dict[tuple[str, str], dict] = {}
        self._persist_deferred: dict[tuple[str, str], tuple[dict, int]] = {}
        self._persist_compactions: list[tuple[str, int]] = []  # (path, tries)
        self._persist_queue_lock = threading.Lock()
        self._persist_wakeup = threading.Event()
        self._persist_writer: threading.Thread | None = None
        self._persist_stop = False
```

`threading` is already imported (:14). **`import os` must be ADDED to the module imports** (currently absent — feed_handler.py:11-21 verified; audit r5 #1 — the size-scaled shutdown uses `os.path.*`). No other new imports.

**2.1.2 New methods** (placed after `update_card`, before `_update_card_visual`):

```python
    def _ensure_persist_writer(self) -> None:
        """Lazily (re)start the background feed writer thread.

        Clears the stop flag BEFORE the liveness check so an enqueue that
        races a shutdown never strands the entry. When a NEW thread is
        started, deferred retries keep their payloads but reset tries to 0
        (a new writer generation = a fresh retry budget; the reset happens
        per new-thread-start — any prior exit: stop or crash — NOT per
        close/reopen cycle).
        """
        self._persist_stop = False
        w = self._persist_writer
        if w is not None and w.is_alive():
            return
        with self._persist_queue_lock:
            self._persist_deferred = {
                k: (payload, 0) for k, (payload, _t) in self._persist_deferred.items()
            }
        self._persist_writer = threading.Thread(
            target=self._persist_loop, name="crabcakes-feed-writer", daemon=True
        )
        self._persist_writer.start()

    def _enqueue_card_update(self, project_path: str, card_id: str, updates: dict) -> None:
        """Queue a card update for background persistence. Non-blocking.

        Contract: callers MUST pass the FULL current metadata (and body).
        Coalescing merges per top-level key via dict.update — a partial
        second update DROPS omitted keys (correct only for full-state
        payloads like update_card's). metadata is copied one level deep; a
        non-dict metadata value is dropped with a WARNING (never journaled).
        A fresh enqueue DISCARDS any deferred entry for the same key — the
        fresh payload supersedes the old retry entirely (fresh budget).
        """
        if not project_path or not card_id:
            return
        payload = dict(updates)
        if "metadata" in payload:
            if isinstance(payload["metadata"], dict):
                payload["metadata"] = dict(payload["metadata"])
            else:
                _logger.warning(
                    "enqueue: non-dict metadata for card %s dropped", card_id
                )
                payload.pop("metadata")
        with self._persist_queue_lock:
            key = (project_path, card_id)
            self._persist_deferred.pop(key, None)   # fresh wins, structurally
            pending = self._persist_queue.get(key)
            if pending is None:
                self._persist_queue[key] = payload
            else:
                pending.update(payload)
        self._ensure_persist_writer()
        self._persist_wakeup.set()

    def _enqueue_compaction(self, project_path: str) -> None:
        """Queue a feed compaction for the writer thread.

        EXTERNAL trigger (load-time): replaces any existing entry for the
        same path with a fresh tries=0 — a load-time enqueue is a new
        attempt and resets the compact budget (distinct from the drain's
        internal retry re-enqueue, which appends only-if-absent with
        incremented tries).
        """
        if not project_path:
            return
        with self._persist_queue_lock:
            self._persist_compactions = [
                t for t in self._persist_compactions if t[0] != project_path
            ] + [(project_path, 0)]
        self._ensure_persist_writer()
        self._persist_wakeup.set()

    def _persist_loop(self) -> None:
        """Writer main loop. Stop-check FIRST; drain-before-exit; bounded.

        Shutdown bound: once the stop flag is observed, at most one more
        drain pass runs; failures during that pass DROP with ERROR (no
        deferral), so the writer exits within one pass of the stop signal.
        """
        while True:
            if self._persist_stop:
                with self._persist_queue_lock:
                    drained = (
                        not self._persist_queue
                        and not self._persist_compactions
                        and not self._persist_deferred
                    )
                if drained:
                    return
            self._persist_wakeup.wait(timeout=0.5)
            self._persist_wakeup.clear()
            self._drain_persist_queue()
            # loop: stop-check at top re-examines after the drain

    def _drain_persist_queue(self) -> None:
        """One full drain pass: compactions, then deferred, then queue.

        Bounded pass: compactions are SNAPSHOTTED at pass start (entries
        enqueued during the pass — internal retries or external triggers —
        wait for the next pass; ≤1 attempt per path per pass regardless of
        source, audit r5 #18). Deferred entries are attempted IN PLACE
        (never moved to the queue — no re-merge, no counter reset, audit r5
        #2/#3). A queue entry's first failure enters deferred with tries=1
        (fresh budget by construction — enqueue always pops any deferred
        entry for the key, so deferred and queue entries for one key are
        mutually exclusive). Never raises: the except blocks only log and
        do dict/list ops under the queue lock; task/kind are initialized
        before the try (audit r5 #15).
        """
        # ── compactions: snapshot at pass start ─────────────────────────
        with self._persist_queue_lock:
            compactions = list(self._persist_compactions)
            self._persist_compactions.clear()
        for compact_task in compactions:
            path, tries = compact_task
            try:
                pruned = feed_store.compact_feed(
                    path, window=feed_store.FEED_WINDOW_DEFAULT
                )
                if pruned:
                    self._surface_prune_card(path, pruned, feed_store.FEED_WINDOW_DEFAULT)
            except Exception:  # noqa: BLE001 — writer thread must never die
                _logger.exception("persist: compact task failed (%r)", compact_task)
                if self._persist_stop:
                    _logger.error(
                        "persist: dropping failed compact during shutdown (%r)",
                        compact_task,
                    )
                elif tries + 1 >= 3:
                    _logger.error(
                        "persist: dropping compaction for %s after %d failures",
                        path, tries + 1,
                    )
                else:
                    with self._persist_queue_lock:
                        # only-if-absent: an external _enqueue_compaction that
                        # landed during the pass owns the live entry (fresh
                        # budget); do not overwrite it
                        if not any(p == path for p, _t in self._persist_compactions):
                            self._persist_compactions.append((path, tries + 1))

        # ── deferred updates: attempted in place ─────────────────────────
        with self._persist_queue_lock:
            deferred_items = list(self._persist_deferred.items())
        for key, (payload, tries) in deferred_items:
            project_path, card_id = key
            try:
                ok = feed_store.update_feed_card(project_path, card_id, payload)
                if ok is False:
                    raise RuntimeError(
                        "update_feed_card returned False (append+legacy failed)"
                    )
                # success — remove OUR entry only (a newer entry may exist)
                with self._persist_queue_lock:
                    cur = self._persist_deferred.get(key)
                    if cur is not None and cur[0] is payload:
                        del self._persist_deferred[key]
            except Exception:  # noqa: BLE001
                _logger.exception("persist: deferred update failed (%r)", key)
                with self._persist_queue_lock:
                    cur = self._persist_deferred.get(key)
                    if cur is None:
                        # a fresh enqueue superseded us — drop the stale retry
                        pass
                    elif cur[0] is not payload:
                        # a newer failure already replaced us — leave it
                        pass
                    elif self._persist_stop:
                        _logger.error(
                            "persist: dropping deferred update during shutdown (%r)",
                            key,
                        )
                        del self._persist_deferred[key]
                    elif tries + 1 >= 3:
                        _logger.error(
                            "persist: dropping update for %r after %d failures",
                            key, tries + 1,
                        )
                        del self._persist_deferred[key]
                    else:
                        self._persist_deferred[key] = (payload, tries + 1)

        # ── queue updates ────────────────────────────────────────────────
        while True:
            kind = None
            task = None
            with self._persist_queue_lock:
                if not self._persist_queue:
                    break
                key, updates = self._persist_queue.popitem()
                task = (key, updates)
            project_path, card_id = key
            if not project_path or not card_id:
                _logger.warning(
                    "persist: dropping malformed queue entry for %r", card_id
                )
                continue
            try:
                ok = feed_store.update_feed_card(project_path, card_id, updates)
                if ok is False:
                    raise RuntimeError(
                        "update_feed_card returned False (append+legacy failed)"
                    )
                if ok is None:
                    # Legacy path: card gone (pruned between enqueue and
                    # drain). Retrying is futile — drop with INFO.
                    _logger.info(
                        "persist: card %s no longer exists in %s; "
                        "update dropped (pruned?)", card_id, project_path,
                    )
                    continue
            except Exception:  # noqa: BLE001 — writer thread must never die
                _logger.exception("persist: update task failed (%r)", task)
                if self._persist_stop:
                    _logger.error(
                        "persist: dropping failed update during shutdown (%r)",
                        key,
                    )
                else:
                    # first failure of THIS payload: fresh budget (any prior
                    # deferred entry was popped by the enqueue that queued it)
                    with self._persist_queue_lock:
                        self._persist_deferred[key] = (updates, 1)

    def shutdown_persist_writer(self) -> None:
        """Flush and stop the writer. Safe to call multiple times.

        Join timeout scales with the feed's size (a 13.9 MB compact can
        exceed a flat 5 s): min(60.0, 5.0 + size_mb). Exit logging
        distinguishes three conditions (audit r5 #4): undrained entries
        (ERROR), a straggler enqueued during shutdown (WARNING — it will
        be drained by the still-alive writer or the next generation), and
        exit not observed though the queue is empty (WARNING).
        """
        self._persist_stop = True
        self._persist_wakeup.set()
        with self._persist_queue_lock:
            queued_at_stop = (
                len(self._persist_queue)
                + len(self._persist_compactions)
                + len(self._persist_deferred)
            )
        if self._persist_writer is not None:
            timeout = 5.0
            try:
                for path in list(self._project_paths.values()):
                    fp = os.path.join(path, ".crabcakes", "feed.json")
                    if os.path.isfile(fp):
                        timeout = min(60.0, 5.0 + os.path.getsize(fp) / 1_000_000)
                        break
            except OSError:
                pass
            self._persist_writer.join(timeout=timeout)
        with self._persist_queue_lock:
            leftover = (
                len(self._persist_queue)
                + len(self._persist_compactions)
                + len(self._persist_deferred)
            )
        if leftover > queued_at_stop:
            _logger.warning(
                "persist shutdown: %d entries enqueued after shutdown began "
                "(stragglers — drained by the writer or next generation)",
                leftover - queued_at_stop,
            )
        if leftover > 0:
            _logger.error(
                "persist writer stopped with %d undrained entries "
                "(in-flight write exceeded join timeout)", leftover,
            )
        elif self._persist_writer is not None and self._persist_writer.is_alive():
            _logger.warning(
                "persist writer still draining at join timeout; queue is empty "
                "— exit not observed, but entries were drained",
            )
```

Note: `feed_store` is the module reference imported at :26 — the function-local import at :1016 goes away with Edit A. `_surface_prune_card` is defined in Phase 3 (§2.3.5). Phase 1 implements the queue/writer WITHOUT the compact branch and `_enqueue_compaction` (compactions arrive with Phase 3's trigger); the snippet shows the final form for review continuity. **Phase-1 interim:** the drain loop's compact branch is absent and the `task` tuple for updates is handled directly — Phase 3 adds the branch verbatim from this snippet.

**Edit A — `update_card` (:963):** replace the synchronous persist block (:1015-1021) with:

```python
        # Phase 1: persist off the main thread (was a synchronous 13.9 MB
        # read-modify-write on the GTK main thread — measured 0.62 s per tool
        # result). Coalesced per (project, card); last-write-wins.
        project_path = self._project_paths.get(card_data.project_name, "")
        if project_path:
            self._enqueue_card_update(project_path, card_id, {
                "body": card_data.body,
                "metadata": card_data.metadata,
            })
```

The widget rebuild and `_replace` dispatch below it are unchanged.

**Edit B — accept/reject paths (:1431, :1492):** replace `feed_store.update_feed_card(project_path, card_id, {"accepted": True})` (and the `False` twin) with `self._enqueue_card_update(project_path, card_id, {"accepted": True})`. Durability note: journaled O(1) by the writer within the wakeup latency (~ms steady-state); a hard kill inside that window can lose the persisted decision (in-memory UI still shows it until restart). Accepted per parent §5.

**Edit C — `ui/window.py` project-close chain (:585-592):** append `self._feed_handler.shutdown_persist_writer(),` as the final tuple element.

**Edit D — `ui/window.py` app close-request (new):** in `MainWindow.__init__` (near the `"realize"` connect at :66):

```python
        self.connect("close-request", self._on_close_request)
```

and:

```python
    def _on_close_request(self, *args) -> bool:
        """Flush the background feed writer before the window destroys."""
        try:
            self._feed_handler.shutdown_persist_writer()
        except Exception:
            logger.exception("close-request: feed writer shutdown failed")
        return False  # allow default close handling
```

No existing `close-request` handler exists (grep-verified) — no conflict.

**Thread-safety contract (for the audit):**
- `update_card` mutates `self._cards[card_id]` under `self._lock` (:978-979) *before* enqueueing; the queue stores a one-level-deep copy. Queue keys carry their own `project_path` — the writer never consults `_project_paths`.
- Ordering: **per-card last-write-wins is strict** (coalescing merge + single writer + fresh-enqueue-discards-deferred). **Cross-card order is best-effort FIFO of drain order** — sufficient (parent §1.4).
- Partial-update contract: callers MUST pass full `metadata`; enforced by documentation + test.
- The writer never touches `_cards`/`_project_seq`/widgets; prune-card UI work rides `GLib.idle_add`. The writer reads `_active_project_name` (single attribute load — atomic under the GIL); the idle callback re-checks it under the same-thread guarantee (main), so a stale read can only cause a suppressed card, never a wrong-project card.
- Daemon thread; hung write cannot block shutdown beyond the 5 s join; leftovers logged at ERROR, never silent.

**Phase 1 invariants:**
1. `update_card` performs no disk I/O — wall time <50 ms on a 9,500-card fixture (design target <5 ms).
2. Per-card last-write-wins holds across coalescing AND retries: enqueue pops any deferred entry for the key (mutual exclusivity ⇒ a queue entry's first failure is always tries=1 — fresh budget by construction, no comparison needed); deferred entries retry in place (tries preserved across passes) (tests).
3. A failing write never strands siblings (test: poison + good entry → good persists in the same pass).
4. Retry caps: updates 3 failures → ERROR drop; compactions 3 failures → ERROR drop; compactions snapshot at pass start — ≤1 attempt per path per pass regardless of source (internal retry or external trigger) (tests).
5. Shutdown bounded: exit within one drain pass of the stop signal; failures during stop DROP with ERROR; join timeout scales with feed size; exit logging is three-way (straggler WARNING / undrained ERROR / exit-not-observed WARNING) (test).
6. Close-then-reopen never strands a new entry; a new writer generation resets deferred tries (payloads kept) — per new-thread-start, not per close/reopen (test).
7. Compaction request never reaches `update_feed_card` as an update (sentinel isolation test).
8. A `None` return from `update_feed_card` (card gone via legacy path) is logged INFO and dropped — never deferred, never retried (test).

### 2.2 Phase 2 — `utils/feed_store.py`

**2.2.1 Module constants + rate-limit state** (after `_LOCK_RETRY_DELAY` at :19):

```python
JOURNAL_FILENAME = "feed-updates.jsonl"
JOURNAL_COMPACT_THRESHOLD = 500   # lines; compact when exceeded
_LOCK_TIMEOUT_SEC = 2.0           # bounded lock deadline (was unbounded)
_COMPACT_MIN_INTERVAL = 60.0      # seconds between append-triggered compacts

# Documented deviation from the module's "pure functions" docstring: the
# compact rate-limit needs per-project last-compact timestamps. Guarded by
# _compact_rl_lock; no GTK, no handler state — file-I/O orchestration only.
_compact_last: dict[str, float] = {}
_compact_rl_lock = threading.Lock()
```

`import threading` added to feed_store's imports (stdlib; utils stays GTK-free).

**2.2.2 Bounded lock — rework `_acquire_lock` (:96-113):**

```python
def _acquire_lock(path: str, timeout: float = _LOCK_TIMEOUT_SEC) -> tuple | None:
    """Acquire the feed lock. Returns (fd, lock_path) or None on timeout.

    Never blocks unbounded: non-blocking attempts inside a deadline loop.
    Callers must handle None — read paths fall back per their own policy;
    write paths skip and log (journal/queue/deferred-retry keeps the data
    safe for the next attempt).
    """
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd, lock_path
        except (OSError, BlockingIOError):
            time.sleep(_LOCK_RETRY_DELAY)
    os.close(fd)
    _logger.warning("feed lock busy >%.1fs: %s", timeout, lock_path)
    return None
```

**2.2.3 Lock discipline — uniform rule:** every feed_store mutation (snapshot or journal) holds the feed flock for its whole critical section. `None` handling:
- `load_feed` (:124): background-thread API (sole production caller `_load_and_render` :1103 in the :1224 daemon thread — verified). Timeout **scales with file size**: `min(60.0, 10.0 + size_bytes / 1_000_000)` s (≥10 MB/s patience vs a ~5 MB/s compact). If still `None`: lock-free read with WARNING; documented narrow residual race (truncate between snapshot and journal reads — requires a compact exceeding the scaled timeout; the next load re-reads consistently).
- `append_feed_card`, `_update_feed_card_legacy`, `save_feed`, `compact_feed`, `append_card_update`: on `None`, skip the write + WARNING; append/update return without writing (`append_card_update` → False).
- `save_feed` **gains** lock acquisition (currently lock-free; no production callers — tests only — but lock-free is a trap). Uncontended in single-threaded tests → existing test files pass.
- `_release_lock` only when acquire succeeded (`if fd is not None`).

**2.2.4 Journal primitives:**

```python
_UPDATABLE_FIELDS = frozenset({"accepted", "reviewed", "metadata", "body"})


def _journal_path(project_path: str) -> str:
    return os.path.join(project_path, ".crabcakes", JOURNAL_FILENAME)


def append_card_update(project_path: str, card_id: str, updates: dict) -> bool:
    """Append one update record to the journal — O(1), no full-file rewrite.

    Record: {"card_id": str, "updates": dict}. Holds the feed flock for the
    check+append (uniform mutation rule — a concurrent compaction can never
    truncate between our append and its fold). A non-dict "metadata" value
    is skipped with a WARNING (type-trust guard, audit r3 #10). Plain
    json.dumps, NO default=: a TypeError returns False with a WARNING — the
    caller falls back to the legacy RMW (correct to_dict serialization).
    Never silently corrupts a value. A torn final line is tolerated by
    replay. Returns True if the line was written.
    """


def _replay_journal(project_path: str) -> dict[str, dict]:
    """Fold the journal into {card_id: merged_updates}.

    Stops at the first unparseable line (torn tail) and logs a warning.
    Missing journal is not an error. Later records merge over earlier ones
    per-key (dict.update).
    """


def _journal_line_count(project_path: str) -> int:
    """Count journal lines (bounded by threshold + in-flight)."""


def _parse_cards(raw) -> list[FeedCardData]:
    """Parse a raw JSON value into cards (shared by load_feed/compact_feed)."""


def _apply_overlay(cards: list[FeedCardData], overlay: dict) -> None:
    """Merge a journal overlay onto parsed cards (shared load/compact rules).

    metadata merges per-key (card.metadata.update(val)) when val is a dict;
    non-dict metadata overlay values are skipped with a WARNING (type-trust
    guard). Scalars setattr. Unknown card_ids skipped (stale record).
    """
```

Implementation notes: `append_card_update` ensures the directory, takes the flock (`None` → False), opens `"a"` (if the file exists, is non-empty, and does not end with `\n`, prepend `\n` so a torn tail stays one line; empty file → no prepend), appends one `f.write` of `json.dumps(...) + "\n"`, `except TypeError/OSError → WARNING + return False`, releases. Gitignore on first journal creation: `_ensure_gitignore_entry(project_path, ".crabcakes/" + JOURNAL_FILENAME)` — **known pre-existing limitation** (the gitignore helper's own read-modify-write is not flock-protected; inherited, documented in the audit log, not fixed here).

**2.2.5 Replay integration — `load_feed` (:124), snapshot + journal under ONE lock hold:**

```python
    fd = None
    lock_path = None
    try:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        timeout = min(60.0, 10.0 + size / 1_000_000)
        fd, lock_path = _acquire_lock(path, timeout=timeout)  # bg-thread API
        if fd is None:
            _logger.warning("load_feed: lock busy >%.1fs, lock-free read of %s",
                            timeout, path)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        overlay = _replay_journal(project_path)   # same lock window
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed: failed to read %s: %s", path, e)
        return []
    finally:
        if fd is not None:
            _release_lock(fd, lock_path)
    cards = _parse_cards(raw)
    _apply_overlay(cards, overlay)
    return cards
```

**2.2.6 Journal-first `update_feed_card` (:227):**

```python
def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool | None:
    """Record a card update. True = safely recorded (journaled or written).

    Hot path O(1): append one journal line (under the flock). Compaction is
    triggered when the journal exceeds JOURNAL_COMPACT_THRESHOLD, but a
    compaction failure does NOT affect the return: the journal line is
    already durable, so True stands and the compact is retried naturally by
    the next threshold crossing (audit r3 #1). Returns False ONLY for a
    write failure (journal append failed AND legacy write failed — lock
    timeout or OSError; the handler writer defers retry). Returns None when
    the legacy path ran and the card was not found (pruned between enqueue
    and drain) — the handler writer logs INFO and drops without retry.
    """
    ok = append_card_update(project_path, card_id, updates)
    if ok:
        try:
            if _journal_line_count(project_path) >= JOURNAL_COMPACT_THRESHOLD:
                compact_feed(project_path, window=FEED_WINDOW_DEFAULT)
        except Exception:  # noqa: BLE001 — compaction is orthogonal
            _logger.warning(
                "update_feed_card: post-append compaction failed for %s "
                "(will retry at next threshold)", project_path,
            )
        return True
    return _update_feed_card_legacy(project_path, card_id, updates)
```

`_update_feed_card_legacy` = the current body verbatim (lock → load → setattr (allowed set `_UPDATABLE_FIELDS`) → write) with **tri-state returns** (audit r4 #14/#18): `True` (found + written), `False` (write failure: lock-timeout skip or OSError), `None` (card not found). The journal path never checks existence (D4); only the legacy fallback can return None.

**2.2.7 Compaction:**

```python
def compact_feed(project_path: str, window: int | None = None) -> int:
    """Fold the journal into feed.json. Returns cards pruned (0 if window None).

    Under the feed flock (single hold): read the snapshot inline via the
    shared _parse_cards (does NOT call load_feed — no lock re-entry), apply
    the overlay via _apply_overlay (same merge rules as load_feed), apply
    the sliding window if window is not None, write the merged snapshot
    atomically (compact JSON), then truncate the journal — all before
    releasing the lock. Crash-safety: snapshot replace FIRST, journal
    truncate SECOND (replay idempotent). Race-safety: readers and journal
    appenders hold the same flock. On success, records the compact in the
    rate-limit map (with _compact_rl_lock: _compact_last[project_path] =
    time.monotonic()) so every trigger path shares one budget.
    """
```

Journal truncation: `open(journal_path, "w").close()` under the lock.

**2.2.8 `append_feed_card` threshold trigger — exact pattern (rate-limited):**

```python
def append_feed_card(project_path: str, card: FeedCardData) -> None:
    # ... existing lock → read → append → write, UNCHANGED ...
    # finally: _release_lock(fd, lock_path)     ← releases BEFORE compact
    # post-append threshold check (outside the lock):
    _maybe_compact(project_path)


def _maybe_compact(project_path: str) -> None:
    """Rate-limited post-append compaction trigger.

    At most one append-triggered compact per project per
    _COMPACT_MIN_INTERVAL (60 s): under a sustained high append rate, a
    compact that takes seconds would otherwise re-trigger on nearly every
    append (the count re-crosses the soft bound while the compact runs —
    audit r3 #5). Called with NO lock held; compact_feed takes its own.
    Concurrent callers serialize on the flock; a loser's compact is a
    harmless no-op fold.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return
    now = time.monotonic()
    with _compact_rl_lock:
        if now - _compact_last.get(project_path, 0.0) < _COMPACT_MIN_INTERVAL:
            return
        _compact_last[project_path] = now
    try:
        with open(path, "r", encoding="utf-8") as f:
            n = len(json.load(f))
    except (OSError, json.JSONDecodeError):
        return
    if n > FEED_WINDOW_DEFAULT * 1.25:
        compact_feed(project_path, window=FEED_WINDOW_DEFAULT)
```

(The rate-limit timestamp is recorded BEFORE the size check — a compact that finds the feed under the bound still spends the interval; prevents re-check thrash. `compact_feed` also records its own timestamp for consistency.)

**2.2.9 Compact serialization — `_atomic_write_json` (:30):** add `compact: bool = False`; when True, `json.dump(data, f)` — no indent, NO `default=` (TypeError must surface, never silently stringify). Feed snapshot callers pass `compact=True`; prefs callers unchanged. `tests/test_low12_13_feed.py` asserts behavior, not format (verified).

**Phase 2 invariants:**
1. `update_feed_card` performs no `json.load` of feed.json on the hot path — journal append on a 9,500-card feed within 3× of an empty feed (test).
2. `feed.json` alone remains valid for journal-unaware readers, except journaled-but-uncompacted updates.
3. Torn final journal line never destroys prior records; replay idempotent (test).
4. Compaction crash-safe AND race-safe (all mutations under the one flock; readers hold it across snapshot+journal reads) (test).
5. `_acquire_lock` returns within its timeout — never unbounded (test).
6. Non-JSON-native payload → WARNING + False → legacy fallback — never a corrupt write, never a crash (test). Non-dict metadata → skipped at enqueue AND at journal write (test).
7. Journal-append success ⇒ `update_feed_card` True even if the post-append compact fails; no duplicate journal lines from deferral loops (test).
8. No flock re-entrancy: `append_feed_card` releases before `_maybe_compact`; `compact_feed` parses inline; `update_feed_card`'s threshold check runs after the append returned (test: no nested acquire).
9. Append-triggered compacts are rate-limited: ≥60 s between per-project auto-compacts; `compact_feed` records the timestamp on success for every trigger path (tests).
10. `update_feed_card` tri-state (audit r4): True = recorded; False = write failure (defer-retry); None = card gone via legacy path (log INFO, drop, never retry) (tests).

### 2.3 Phase 3 — sliding-window pruning (`utils/feed_store.py` + `ui/handlers/feed_handler.py`)

**2.3.1 Constant:**

```python
FEED_WINDOW_DEFAULT = 2000        # newest N cards retained at compaction
```

(No `feed-meta.json` — D1.)

**2.3.2 Retention rules inside `compact_feed`:** a card is **pinned** (never pruned) if any of: `accepted is not None`; `metadata.get("needs_review")` or `metadata.get("needs_approval")`; `card_type == "git_commit"`. Keep the newest `window` by list order (`[-window:]`), then additionally pin any card outside that slice matching the rules. Prune the rest. Log at WARNING.

**2.3.3 Compaction triggers (D6):** `update_feed_card` threshold (Phase 2 form — compaction failure retried at next crossing); `append_feed_card` post-append via rate-limited `_maybe_compact` (§2.2.8); `load_feed` never compacts.

**2.3.4 One-time large-feed compaction on project open:** in `_load_and_render` (:1103, background thread), after `cards = feed_store.load_feed(project_path)`, if `len(cards) > FEED_WINDOW_DEFAULT * 1.25`: log and `self._enqueue_compaction(project_path)` (writer runs it; failures re-enqueue with cap 3 per §2.1.2). **Accepted latency (round-1 BUG #6):** first tool results after a legacy-feed open may wait behind the compaction — one-time upgrade cost.

**2.3.5 Prune surfacing — `feed_handler._surface_prune_card(project_path, pruned, window)`** (writer thread). The writer NEVER calls `add_card` (its `_project_seq` RMW at :713-716 is unsynchronized and `build_feed_card` constructs GTK widgets — both main-thread-only; auditor-verified facts):

```python
    def _surface_prune_card(self, project_path: str, pruned: int, window: int) -> None:
        """Surface a compaction as a UI system card. Called on the writer.

        UI work (add_card: seq assignment, widget build, indexing) happens
        on the MAIN thread via idle_add. Persistence writes a point-in-time
        COPY of the card state (deep-copied on the main thread inside _ui)
        from a tiny persist thread — bypassing add_card's _loading-gated
        persist (audit r1 #9) and immune to post-add in-memory mutation
        (audit r3 #7). System cards never carry snapshots (no file_path ⇒
        _maybe_create_snapshot no-ops), so the copy is always complete.
        """
        card = FeedCardData(
            card_type="system",
            source="system",
            title="Feed compacted",
            body=f"{pruned} oldest cards pruned (window {window})",
            author="system",
            timestamp=datetime.now(timezone.utc),
            project_name=self._active_project_name or "",
        )

        def _ui():
            # Main thread: guard against the project closing mid-compaction.
            if not card.project_name or self._active_project_name != card.project_name:
                return
            self.add_card(card, persist=False)   # seq, widgets, indexing — main only
            snapshot = copy.deepcopy(card)        # point-in-time copy, main thread
            def _persist():
                feed_store.append_feed_card(project_path, snapshot)
            threading.Thread(target=_persist, daemon=True).start()

        self._GLib.idle_add(_ui)
```

(`copy` and `datetime`/`timezone` added to feed_handler's module imports — both stdlib.)

**`add_card` gains `persist: bool = True`** keyword (:700 → `def add_card(self, card_data: FeedCardData, persist: bool = True) -> str:`); the persist condition (:810) becomes `if project_path and not self._loading and persist:`. All existing callers are positional on `card_data` — no breakage.

**2.3.6 Stale-update tolerance:** `update_card`'s early-return (:974-976) and the replay drop stay non-raising; compaction logs dropped stale journal lines at DEBUG.

**Phase 3 invariants:**
1. No actionable card (pending decision, needs_review, needs_approval) is ever pruned; no `accepted` decision is ever pruned; git_commit cards are never pruned.
2. `seq_num` monotonic across compaction (handler rebuild; test).
3. Pruning logged + surfaced: card shown AND persisted (from the copy) including when the race lands during `_loading`; suppressed when the project closed before the idle callback (tests).
4. After one-time compaction: `load_feed` <100 ms at the window default (9,500-card fixture; test).
5. Compaction request never reaches `update_feed_card` as an update (test).
6. The writer thread never calls `add_card` / touches `_cards` / `_project_seq` / widgets — enforced structurally (`add_card` appears only inside the `_ui` closure) and tested two ways: (a) a **recording GLib fake** (queue-only, manual `fire()` on the test thread) — assert `add_card` NOT called before `fire()`, called after; (b) an **AST structural test**: parse `feed_handler.py`, find `_surface_prune_card`, assert every `add_card` call node lies inside a nested function def, none directly in the method body. (The existing sync `MockGLib` runs callbacks on the calling thread — it cannot express "main thread only"; the recording fake can. Existing MockGLib is untouched.)

---

## 3. Data flow (after all three phases)

```
Tool result (runtime thread)
  → _on_tool_call_result → GLib.idle_add → _do_tool_call_result [main]
    → feed_handler.update_card [main]
        mutate self._cards under _lock; rebuild/replace widget   [main, ~ms]
        _enqueue_card_update(project, card_id, {body, metadata}) [main, <1 ms, no disk]
  → crabcakes-feed-writer thread [background]
    → feed_store.update_feed_card
        append_card_update → 1 JSONL line (flock held briefly)    [O(1)]
        if journal ≥ 500 → compact_feed(window=2000)              [no lock held]
            fold (shared _parse_cards/_apply_overlay) → prune (pins)
            → atomic compact snapshot write → truncate journal   [one flock hold]
Project open [main: on_project_opened]
  → _load_and_render [background thread :1224]
      load_feed: snapshot + journal under one flock hold (size-scaled timeout)
      if len(cards) > 2500 → _enqueue_compaction           [writer runs it]
Compaction pruned >0 → _surface_prune_card [writer]
  → GLib.idle_add → _ui [main]: add_card(persist=False) + deepcopy
      → tiny persist thread: append_feed_card(copy) → _maybe_compact (rate-limited)
```

Accept/reject clicks follow the update queue (Edit B). `add_card`/`add_cards_batch` persist via their existing per-card threads → `append_feed_card` (lock released → rate-limited `_maybe_compact` when oversized). **Multiple threads call `append_feed_card` (per-card persist threads, batch thread, prune persist thread) — the flock serializes them; that is the concurrency contract, not "a single writer thread."**

## 4. File change summary

| File | Phase | Change | Est. lines | Risk |
|---|---|---|---|---|
| `ui/handlers/feed_handler.py` | 1 | writer thread, enqueue, deferred-retry, Edits A/B | +140 | MED |
| `ui/window.py` | 1 | Edit C + Edit D close-request | +10 | LOW |
| `utils/feed_store.py` | 2 | journal, replay, compact, bounded lock, compact JSON, `save_feed` lock, `_maybe_compact`, shared parse/merge helpers | +190 | MED |
| `utils/feed_store.py` | 3 | window, pins | +40 | MED (retention rules) |
| `ui/handlers/feed_handler.py` | 3 | compaction wiring, load-time trigger, `add_card(persist=)`, `_surface_prune_card` | +55 | LOW |
| `tests/test_feed_store.py` | 2,3 | ~16 new/updated tests | +300 | LOW |
| `tests/test_feed_handler.py` | 1,3 | ~10 new tests (incl. recording GLib fake + AST test) | +200 | LOW |
| `docs/ARCHITECTURE.md` | 3 | feed persistence sections (§8 grep targets) | +25 | LOW |

## 5. Implementation order

1. **Phase 1** (feed_handler + window) — red tests first (`TestBackgroundPersistWriter`: immediacy, coalescing, poison-no-strand, retry cap, fresh-discards-deferred, bounded shutdown incl. drop-during-stop, malformed-entry drop, close-then-reopen restart + tries reset), then code, then existing suites green.
2. **Phase 2** (feed_store) — red tests first (O(1) append, replay idempotent, torn tail, compaction folds+truncates under one lock, lock timeout incl. size-scaled, serialization-failure fallback, non-dict metadata guards, save_feed lock, no nested acquire, True-despite-compact-failure, rate limit), then code, then the 13 existing feed_store tests + rewritten `test_update_nonexistent_returns_false`.
3. **Phase 3** (window + pins + triggers) — red tests first (pin rules, seq monotonic, load-time trigger + compact retry cap, sentinel isolation, prune-card persisted-despite-`_loading` via copy + suppressed on closed project, <100 ms load at window, main-thread structural tests), then code.
4. ARCHITECTURE.md update + full-suite baseline comparison + post-mortem.

Each phase: Coder builds (steelFramedCodeWriter) → Debugger adversarial audit (adversarialDebugger) → supervisor independent verification → next.

## 6. Acceptance criteria

**Latency (enqueue vs. persistence are different bounds):**
- [ ] Main-thread `update_card` wall time <50 ms with a 9,500-card fixture (design target <5 ms) — no disk I/O on the main-thread path (test)
- [ ] Persisted ≤0.6 s after enqueue in steady state (test)

**Writer correctness:**
- [ ] N enqueues for one card → 1 writer call; final state = last update (test)
- [ ] Poison entry does not strand siblings; update retry cap 3 → ERROR drop; compact retry cap 3 → ERROR drop; compactions snapshot at pass start (≤1 attempt per path per pass) (tests)
- [ ] Enqueue pops any deferred entry for its key — a queue entry's first failure is tries=1 (fresh budget, no comparison); deferred entries retry in place with tries preserved (tests)
- [ ] Shutdown bounded: exit within one drain pass of the stop signal; drop-during-stop logged; join timeout scales with feed size; three-way exit logging (straggler/undrained/exit-not-observed) (test)
- [ ] Close-then-reopen never strands a new entry; new generation resets tries (test)
- [ ] Compaction request never reaches `update_feed_card` as an update (test)

**Journal:**
- [ ] Journal append O(1): 9,500-card feed within 3× empty feed (test)
- [ ] Replay idempotent; torn tail tolerated with exactly one warning (test)
- [ ] Compaction folds + truncates under one lock hold; no nested lock acquire anywhere in feed_store (test)
- [ ] `_acquire_lock` returns `None` within timeout against a held lock — never unbounded; load timeout scales with file size (tests)
- [ ] Non-JSON-native payload → WARNING + False → legacy fallback; non-dict metadata dropped at enqueue AND journal write — never a corrupt write, never a crash (tests)
- [ ] Journal-append success ⇒ True even when the post-append compact fails; no duplicate journal lines from deferral (test)
- [ ] Append-triggered compacts rate-limited ≥60 s apart per project; `compact_feed` records the timestamp on success for every trigger path (test)
- [ ] `update_feed_card` tri-state: True/False/None per D4 + audit r4 — None (card gone) never deferred by the writer (tests)

**Pruning:**
- [ ] Pin rules hold (test)
- [ ] `seq_num` monotonic across compaction (test)
- [ ] One-time compaction: 9,500-card fixture → `load_feed` <100 ms post-compaction (test)
- [ ] Prune card shown AND persisted (point-in-time copy) despite `_loading`; suppressed when project closed first (tests)

**Behavior fixes + regression gates:**
- [ ] `body` updates persist (D3 regression test)
- [ ] All 13 original feed_store tests pass (1 rewritten per D4)
- [ ] test_feed_handler.py suite green; full-suite failure set byte-identical to baseline 352caf7 (40 failures)
- [ ] pyflakes undefined-name count unchanged (0 new)
- [ ] Evidence: before/after timings pasted per phase

## 7. Edge cases

| Case | Expected |
|---|---|
| Journal missing | replay → empty overlay |
| Journal torn final line | prior records applied; one warning; next append prepends `\n` if needed (empty file: no prepend) |
| Lock held past deadline (mutation paths) | `_acquire_lock` → None → write skipped + WARNING → handler defers retry |
| Lock held past scaled deadline (load path) | lock-free read with WARNING; narrow documented race; next load consistent |
| Update for pruned card (journal path) | journaled (True); replay drops; compaction drops stale line; DEBUG log |
| Update for pruned card (legacy fallback path) | returns None; writer logs INFO and drops — never deferred, never retried |
| Empty `updates` dict | journaled no-op record |
| `card_id`/`project_path` empty | dropped at enqueue; malformed queue entries dropped with WARNING |
| Feed smaller than window | no pruning; journal still folded |
| All cards pinned | prune count 0; log reflects it |
| Two projects, one closes | writer stopped on close, lazily restarted; queue keys carry their own paths |
| Hard kill mid-compaction | snapshot replaced or not; journal intact → replay idempotent → consistent either way |
| Writer fails 3× on one entry | dropped with ERROR; siblings unaffected (same pass) |
| Metadata value not JSON-native / not a dict | WARNING + False → legacy fallback / dropped at enqueue — never journaled garbage |
| Enqueue races shutdown | stop cleared before liveness check; straggler drained by the re-check or dropped-with-ERROR inside the bounded final pass |
| Prune idle callback after project close | UI add skipped (active-project guard); persistence already done from the copy |
| Compaction running when appends trigger | multiple append threads serialize on the flock; rate limit bounds auto-compacts; journal appends and compacts never interleave unprotected |
| Persistent write failures at shutdown | entries dropped with ERROR inside the bounded final pass — shutdown never loops on failures |

## 8. ARCHITECTURE.md updates (final phase)

Find targets by grep, then update:
- `grep -n "feed.json\|feed_store\|append_feed_card\|update_feed_card" docs/ARCHITECTURE.md` — sections describing feed persistence get: the background writer + journal + window model, the uniform flock rule ("every feed_store mutation holds the feed flock; no unbounded blocking lock on any path reachable from the main thread"), the pin rules, the compaction triggers + rate limit, the file inventory addition (`feed-updates.jsonl`), and the documented rate-limit module-state deviation in feed_store's docstring.

## 9. Test-fixture note (shared across phases)

Perf tests use a synthetic `make_feed(n)` builder in `tests/test_feed_store.py` (existing `make_card` helper). Timing assertions use generous multipliers (3×, 50 ms, 100 ms, 0.6 s); each timing test also has a non-timing structural assertion so a flake never masks a functional break. The main-thread-invariant tests use a NEW recording GLib fake local to the new test class (queue-only + `fire()`); the existing sync `MockGLib` used by other tests is untouched.

## 10. Build-time notes for the Coder (from the spec-audit exit round)

1. **Shutdown log conflation (r6#5, accepted):** when some originals were drained and stragglers arrived during shutdown, the undrained-ERROR covers both classes. Write a test that pins this exact behavior (mixed case → ERROR fires with the total count) so the pragmatism is deliberate, not accidental.
2. **Compact budget reset by external trigger (r6#15, accepted):** an external `_enqueue_compaction` resets the path's retry budget. Add a comment at the reset site citing this acceptance; no behavior change.
3. **Identity-guard wording:** the deferred-phase guards are defensive-only (mutual exclusivity makes them unreachable); keep them, comment them as such, do not "simplify" them away during implementation.
4. **Timing-test discipline (§9):** every timing assertion pairs with a structural assertion.
5. **Red-first:** every new behavior test must be demonstrated failing against the pre-change code before the fix lands (the AC3 discipline).
