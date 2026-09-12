# SPEC: UI Responsiveness 2 — Feed Write Path, Main-Thread Offloads, Lock Sharding

**Date:** 2026-09-11
**Author:** Supervisor (per PM direction following the 2026-09-11 live investigation)
**Status:** Draft — for implementation
**Depends on:** SPEC-AUDIT-CLEANUP-3 / AC3 perf quick wins (delta coalescing, 500ms render throttle, single 250ms ticker — all landed); SPEC-UI-RESPONSIVENESS Phase 1 (defer_prompt_build, set_text streaming)
**Supersedes:** the unimplemented remainder of `docs/proposals/PROPOSAL-ui-responsiveness-during-agent-runs.md` (Fixes 4 and 6) — both are carried here as Phase 4
**Supersedes (partially):** `docs/specs/SPEC-UI-RESPONSIVENESS.md` (Phase 1 spec) — its Phase 1 fixes landed; its deferred Phase 2 items live here
**Related / evidence:** `docs/audits/2026-09-01-core-loop-performance.md` (findings #1–#7 — disposition table below)

> **Status of this document.** This spec is the single authoritative *action list* for Crabcakes UI responsiveness. It does **not** erase the two prior documents: the 2026-09-01 audit and the 2026-07-20 proposal remain the historical record of how each finding was discovered and why the earlier fix choices were made. What this spec owns is the disposition of every finding — what shipped, what is scheduled here, and what is deliberately dropped. §0a is that ledger; if a responsiveness question is not answered by §0a, it belongs in a new spec, not in a silent amendment to this one.

---

## 0a. Lineage — disposition of every prior finding (Rule: nothing dropped silently)

| Source | Finding | Status |
|---|---|---|
| Audit #1 | GIL starvation — runtime/SSE/tools in the GTK process | **Not fixed. Phase 8 — spike write-up only** (PM-ruled 2026-09-11: separate spec to follow). Profiler found no samples here in the 09-11 capture. |
| Audit #2 | Per-delta `GLib.idle_add` flood | **FIXED** — AC3 Part A producer-side coalescing (`bc56b50`). |
| Audit #3 | Full-cumulative `set_text` — O(n²) streaming | **FIXED** — AC3 Part B `set_text` + 500 ms throttle + unchanged-skip (`4568cb0`). |
| Audit #4 | Runtime global lock during hot paths | **Open. Phase 6** (per-session lock sharding). Not sampled hot on 09-11, scheduled after Phases 1–3. |
| Audit #5 | FeedBar/activity timers (200 ms × several) | **FIXED** — AC3 Part C single 250 ms ticker + skip-cache (`5e2ebaf`). |
| Audit #6 | Final-render cost spike at `end_streaming` | **Open. Phase 7** (incremental finalize + per-instance pool). |
| Audit #7a | `os.walk` on the runtime thread (`agent/tools.py:479`) | **Dropped from this spec. §9** — no samples in the 09-11 capture; belongs to a future tool-layer pass. |
| Audit #7b | `time.sleep(wait_s)` retry blocks a thread in `agent/llm/streaming.py` | **Dropped from this spec. §9** — thread-pool waste only, never touches the main thread; no samples captured. |
| Audit #7c | `ui/views/file_tree.py` thread-per-operation | **Dropped from this spec. §9** — no samples in the 09-11 capture; revisit only if the file tree is implicated later. |
| Audit #7d | Render pool `max_workers=2` shared as a class attribute | **Open. Phase 7** — confirmed in code at `chat_render_handler.py:215`. |
| Proposal Fix 1 | `build_system_prompt` on the main thread | **FIXED** — Phase 1 `defer_prompt_build` + `_ensure_system_prompt` (`agent/runtime.py:806`, `:892`, `:1268`). |
| Proposal Fix 2 | Double `idle_add` per delta | **FIXED** — AC3 Part B (`chat_render_handler.py:544`, direct `set_text`). |
| Proposal Fix 3 | Throttle at `_do_text_delta` | **FIXED** — AC3 Part A (`agent_runtime_handler.py:1056-1062`). |
| Proposal Fix 4 | Full feed-card widget rebuild on every update | **Open. Phase 4 Part A.** |
| Proposal Fix 5 | `set_markup` during streaming | **FIXED** — AC3 Part B. |
| Proposal Fix 6 | Pre-loop work (load/rebuild/state sync) on the main thread | **Open. Phase 4 Part B** — carried into this spec (the header previously claimed it was superseded without specifying it; corrected). |
| Investigation 09-11 | Feed read+write on the main thread; unbounded feed; unbounded lock wait | **Open. Phases 1–3** (primary). |

---

## DISCOVERY (Rule 1 — read before writing)

- Read `utils/feed_store.py` (431 lines): `update_feed_card` (:227) acquires the flock (:239), `json.load`s the entire file (:243-244), constructs `FeedCardData.from_dict` for **every** card (:249-255), applies `setattr` for the one matching card (:257-268), then `_atomic_write_json(path, [cd.to_dict() for cd in cards])` (:264) — re-serializing every card at `indent=2` (:38). `append_feed_card` (:190) has the same load-all → append-one → write-all shape. `load_feed` (:124) parses all cards. `save_feed` (:169). Lock helpers `_acquire_lock` (:96) / `_release_lock` (:116) — non-blocking flock with 5 retries + blocking final attempt. Module docstring (:1-8) states the pure-function contract: "Pure functions — no GTK, no state, no side effects beyond file I/O."
- Read `ui/handlers/feed_handler.py` (1897 lines): `update_card` (:963) rebuilds the card widget via `build_feed_card` (:986/:992) and then calls `feed_store.update_feed_card(project_path, card_id, updates)` **synchronously on the calling thread** (:1020). `add_card`'s persist path, by contrast, is already backgrounded — `threading.Thread(target=_persist, daemon=True).start()` (:809-812). `PAGE_SIZE = 15` (:89); `_backlog` (:87, populated :1149-1151); "Load More" widget (:1178-1198); accept path calls `feed_store.update_feed_card(..., {"accepted": True})` synchronously (:1431); reject path the same (:1492). `on_filesystem_event` (:1595) calls `conversation_store.snapshot_from_git_diff` inline (:1619). `_finalize_snapshot` (:1623) is scheduled via `GLib.idle_add` (:731, :895) and calls `_maybe_create_snapshot` (:1657) → widget walk `_extract_messages_from_chat_box` (:1706) or `snapshot_from_git_diff` (:1678). Snapshot size guard (:1686). `_load_and_render` reads via `feed_store.load_feed(project_path)` (:1103) and builds widgets only for the newest `PAGE_SIZE` cards (:1173).
- Read `ui/handlers/agent_runtime_handler.py` (1986 lines): `_do_tool_call_result` (:1300) runs on the **main thread** (dispatched by `_on_tool_call_result` :1288 via `GLib.idle_add` :1294) and calls `self._fh.update_card(card_id, card)` at :1345. Approval path calls it at :671. Therefore every tool result triggers the full-file feed rewrite on the GTK main thread.
- Read `agent/runtime.py` (2734 lines): `_dispatch` (:573) wraps callbacks in `GLib.idle_add` — confirming handler `_on_*` callbacks execute on the main thread in production (this is the AC3 post-mortem's `execution-context-map` lesson, §6.1). `self._lock = threading.Lock()` (:510) — one runtime-global lock, no per-session sharding. Audit #4.
- Read `ui/handlers/chat_render_handler.py`: `_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crabcakes-render")` declared as a **class attribute** (:215) — shared across all tabs/sessions. `end_streaming` (:623) replaces the plain streaming bubble with the fully formatted one (`process_segments` → `_assemble_from_processed` :74) on the main thread. Audit #6.
- Read `utils/git_ops.py`: `diff_working_tree` (:312), `status` (:329), `status_porcelain` (:339) — all shell out via `_subprocess.run(..., capture_output=True, text=True, timeout=10)` (:353-356). Each call forks a process and, on a large working tree, does real filesystem work while the caller (main thread) waits.
- Read `agent/tools.py`: `os.walk` over the project tree on the runtime thread (:479) with noise-dir pruning — GIL load during tool loops. Audit #7.
- Read `models/feed_card.py`: `FeedCardData` (:43) — runtime fields `card_id` (:68), `reviewed` (:69), `accepted` (:70), `seq_num` (:71); `to_dict`/`from_dict` round-trip the whole dataclass including `conversation_snapshot` (:65).
- Read `tests/test_feed_store.py`: 13 tests covering round-trip, append, update, malformed JSON, malformed card items. `tests/test_feed_handler.py` (3616 lines) covers handler behavior. `tests/test_low12_13_feed.py` covers the atomic-write/gitignore helpers.
- **Live measurements taken 2026-09-11 against the running app (PID 459641) and a copy of the real feed:**
  - `.crabcakes/feed.json` = **13,925,022 bytes (13.9 MB), 9,500 cards**, avg 1,466 bytes/card.
  - `load_feed()` (json.load + 9,500 × `from_dict`) = **0.24 s**.
  - `update_feed_card()` (lock + read + 9,500 × `from_dict` + 9,500 × `to_dict` + `indent=2` write) = **0.62 s**.
  - `json.dumps(indent=2)` alone = 0.31 s of that; `indent=2` roughly doubles output size vs compact.
  - Main-thread CPU sampled at 3 s intervals: **0 % baseline with 3–6 s bursts pinned at 100 % of a core**, repeatedly, including while no agent turn was active.
  - Process: 20 threads, 1.5 GB RSS, 83 % CPU, 153 min CPU time.
  - No pruning, compaction, rotation, or card cap exists anywhere (grep across `utils/feed_store.py`, `ui/handlers/feed_handler.py` for `prune|compact|trim|max_cards|MAX_FEED|rotate` returns nothing).
- **Root cause:** `update_feed_card` is an O(total feed size) read-modify-write executed on the GTK main thread once per tool result, on a file that grows without bound. GTK surfaces "not responding" after ~5 s of unserviced main loop; a handful of tool calls per turn (0.6 s each, plus widget rebuild and activity bubbles) crosses that threshold, and the cost grows every day as the feed grows.

---

## 0. Live attribution — py-spy capture, 2026-09-11 (added post-write)

Captured against the running app (PID 459641) during a live agent run with tool approvals: 25–29 stack dumps at 3 s intervals plus a 90 s flamegraph (8,718 samples at 100 Hz). Files: `/tmp/crabcakes-stacks.txt`, `/tmp/crabcakes-flame.svg`.

**Result: 100 % of main-thread samples are in the feed-persistence path. Zero samples in any other code path** (no tiktoken, no `os.walk`, no git, no render/markup work).

| Main-thread samples | Path |
|---|---|
| 10 | `json.load` of the whole feed — `update_feed_card (feed_store.py:244)` ← `update_card (feed_handler.py:1020)` ← `_do_tool_call_result (agent_runtime_handler.py:1345)` ← GLib main loop |
| 8 | `json.dump` of the whole feed — `_atomic_write_json (feed_store.py:38)` ← `update_feed_card:264` |
| 9 | **blocked in `_acquire_lock (feed_store.py:112)`** — the blocking `fcntl.flock` fallback, waiting for the feed lock |
| 2 | `is_in_container` ← `replace_card` ← `_replace` (feed card widget swap) |
| 10 | idle (main loop between events) |

Two call chains observed for the same work:
- `_do_tool_call_result` (:1345) — every tool result
- `approve_exec` (:671) ← `handle_approve_exec` (:1757) ← `_auto_approve_exec_card` (:1779) — every auto-approved exec card

Flamegraph (all threads, inclusive samples; top frames by count are **all** feed JSON work):

| Samples | % | Frame |
|---|---|---|
| 748 | 8.58 % | `append_feed_card (feed_store.py:205)` — json.load in the **background** persist thread |
| 678 | 7.78 % | `_atomic_write_json (feed_store.py:38)` |
| 664 | 7.62 % | `append_feed_card (feed_store.py:214)` |
| 595 | 6.83 % | `dump (json/__init__.py:179)` |
| 545 | 6.25 % | `update_feed_card (feed_store.py:244)` — main-thread read |
| 465 | 5.34 % | `update_feed_card (feed_store.py:264)` — main-thread write |
| 433 | 4.97 % | `update_feed_card (feed_store.py:253)` — main-thread `from_dict` loop |
| 396 | 4.54 % | `to_dict (models/feed_card.py:148)` |

**Consequences for this spec:**

1. **Phases 1–3 are the whole fix.** The main thread never samples anywhere else; the GIL/architecture item (Phase 8) and the git/render/lock items (Phases 5–7) are not currently observable hot spots. They stay in the spec as hygiene, but they should not be scheduled ahead of the feed work.
2. **New hazard — unbounded main-thread lock wait.** `_acquire_lock` (:104-113) retries 5× non-blocking, then falls through to a **blocking `fcntl.flock(fd, fcntl.LOCK_EX)` with no timeout** (:112). The dumps caught the main thread parked there 9 times, waiting on the background `append_feed_card` writer. On the main thread this is an unbounded UI stall with no upper bound — strictly worse than a slow parse. Phase 1 must eliminate main-thread lock acquisition entirely; Phase 2 must give the lock helper a bounded timeout and a documented failure mode.
3. **`append_feed_card` is also O(feed size)** — the "backgrounded" write is not free, it just doesn't block the UI; it still burns a core and holds the lock (which is what stalls the main thread). Phase 2's append path applies to it too.

---

## 1. Overview

### 1.1 Problem

The app freezes ("not responding") while agents work. The dominant remaining cost is the feed persistence path:

1. **Synchronous, main-thread, whole-file rewrite.** `feed_handler.update_card` (:1020) calls `feed_store.update_feed_card` inline from `_do_tool_call_result` (:1345) — a main-thread `idle_add` body. Measured **0.62 s per tool result** on the real 13.9 MB feed.
2. **No append path for updates.** Updating one card parses and re-serializes all 9,500 cards, at `indent=2`.
3. **Unbounded growth.** Nothing prunes the feed. Every tool call adds a card, so per-update cost rises monotonically — the reported "getting very annoying" trajectory.
4. **Main-thread git subprocesses.** `on_filesystem_event` (:1619) and `_finalize_snapshot` (:1623, idle-dispatched at :731/:895) run `git diff`/`git status` (10 s timeout, `git_ops.py:353`) on the main thread, once per file-change card — during agent runs, file writes are constant.
5. **Lock contention.** One runtime-global `threading.Lock` (`agent/runtime.py:510`) serializes sessions; audit #4.
6. **Final-render spike + shared render pool.** `end_streaming` (:623) builds the formatted bubble on the main thread; the pool is a class attribute capped at 2 workers shared by every tab (`chat_render_handler.py:215`); audit #6/#7.

### 1.2 Solution

Three structural changes to the feed, then four targeted offloads:

- **Phase 1 — Background + coalesced writes.** Move feed persistence off the main thread into a single per-project writer with last-write-wins coalescing, mirroring the backgrounding `add_card` already does.
- **Phase 2 — Append-only update journal + compaction.** Updates append one line to `feed-updates.jsonl` (O(1)) instead of rewriting the snapshot; `load_feed` replays the journal; compaction folds the journal into the snapshot when it exceeds a threshold.
- **Phase 3 — Sliding-window pruning.** Bound the snapshot to the newest N cards (default 2,000) at compaction time, with hard retention rules for cards that can still be acted on.
- **Phase 4 — Deferred feed-card rendering** (proposal Fix 4, never implemented) and activity-bubble batching.
- **Phase 5 — Git off the main thread** (audit #4-adjacent / finding 4 above).
- **Phase 6 — Per-session lock sharding** (audit #4).
- **Phase 7 — Final-render spike + per-tab render pool cap** (audit #6/#7).
- **Phase 8 — Spike only:** the architectural one-process/GIL item (audit #1) is explicitly **out of implementation scope here** and requires its own spec (see §9).

### 1.3 Scope

| In | Out |
|---|---|
| `utils/feed_store.py` — journal append, compaction, pruning, compact serialization option | `agent/runtime.py` `_run_loop` restructuring (Phase 8 spike territory) |
| `ui/handlers/feed_handler.py` — background writer, coalescing, git offload, deferred card render | Any change to the `FeedCardData` on-disk field set |
| `ui/handlers/agent_runtime_handler.py` — call-site adjustments for async persistence | `gateway/` paths (no feed persistence — grep-verified) |
| `ui/handlers/chat_render_handler.py` — render pool scoping | Rewriting the render pipeline |
| `agent/runtime.py` — per-session lock sharding (Phase 6 only) | Any behavioural change to job/turn state machines |
| `tests/test_feed_store.py`, `tests/test_feed_handler.py` — new + updated tests | Migration of existing project feeds is in scope; **silent data loss is not** |

### 1.4 Architecture principles that apply

- `utils/` stays pure and GTK-free; concurrency lives in the handler layer.
- Main-thread-only GTK work; nothing that blocks >50 ms may run in an `idle_add` body.
- Persistence must be crash-safe: atomic replace, no partial files, no lost accepted/rejected state.
- Ordering: a card's updates must be applied in the order they were produced (last-write-wins per card is acceptable; cross-card reordering is not observable).
- No silent failure: if a write is dropped or a card was pruned, it must be logged, never swallowed.

---

## 2. Changes by File

### 2.1 Phase 1 — Background + coalesced feed writes

**2.1.1 `ui/handlers/feed_handler.py` — add a single coalescing writer**

New instance state (in `__init__`, near `self._lock` at :82):

```python
        # ── Phase 1: background feed persistence ──────────────────────
        # One writer thread per handler. Producers enqueue (project_path,
        # card_id, updates); the dict coalesces repeated updates for the same
        # (project, card) so a burst of tool results costs one write each,
        # never one write per enqueue.
        self._persist_queue: dict[tuple[str, str], dict] = {}
        self._persist_queue_lock = threading.Lock()
        self._persist_wakeup = threading.Event()
        self._persist_writer: threading.Thread | None = None
        self._persist_stop = False
```

New methods:

```python
    def _ensure_persist_writer(self) -> None:
        """Lazily start the background feed writer thread."""
        if self._persist_writer is not None and self._persist_writer.is_alive():
            return
        self._persist_writer = threading.Thread(
            target=self._persist_loop, name="crabcakes-feed-writer", daemon=True
        )
        self._persist_writer.start()

    def _enqueue_card_update(self, project_path: str, card_id: str, updates: dict) -> None:
        """Queue a card update for background persistence (non-blocking).

        Coalescing: a second update for the same (project, card) before the
        writer drains replaces the first — last-write-wins, which matches the
        producer contract (the newest card object is always the authoritative
        one; see FeedCardData.body/metadata assignment in update_card).
        """
        if not project_path:
            return
        with self._persist_queue_lock:
            key = (project_path, card_id)
            pending = self._persist_queue.get(key)
            if pending is None:
                self._persist_queue[key] = dict(updates)
            else:
                pending.update(updates)
        self._ensure_persist_writer()
        self._persist_wakeup.set()

    def _persist_loop(self) -> None:
        """Drain the update queue; one write per (project, card) pair."""
        while not self._persist_stop:
            self._persist_wakeup.wait(timeout=0.5)
            self._persist_wakeup.clear()
            while True:
                with self._persist_queue_lock:
                    if not self._persist_queue:
                        break
                    key, updates = self._persist_queue.popitem()
                project_path, card_id = key
                try:
                    from utils import feed_store
                    ok = feed_store.update_feed_card(project_path, card_id, updates)
                    if not ok:
                        _logger.warning(
                            "persist: card %s not found in %s (pruned or removed)",
                            card_id, project_path,
                        )
                except Exception:  # noqa: BLE001 - writer thread must never die
                    _logger.exception("persist: update failed for %s in %s", card_id, project_path)

    def shutdown_persist_writer(self) -> None:
        """Flush and stop the writer (called from the window shutdown path)."""
        self._persist_stop = True
        self._persist_wakeup.set()
        if self._persist_writer is not None:
            self._persist_writer.join(timeout=2.0)
```

**Edit A — `update_card` (:963):** replace the inline synchronous call at :1020 with the enqueue:

```python
        # Phase 1: persist off the main thread (was a synchronous 13.9 MB
        # read-modify-write on the GTK main thread — measured 0.62 s per tool
        # result). Coalesced per (project, card); last-write-wins.
        if project_path:
            self._enqueue_card_update(project_path, card_id, {
                "body": card_data.body,
                "metadata": card_data.metadata,
            })
```

The widget replacement below it (:1022-1035) is unchanged — it is already an `idle_add` and is cheap.

**Edit B — accept/reject paths (:1431, :1492):** these currently call `feed_store.update_feed_card(...)` synchronously from a UI callback. Route them through the same queue so a burst of accepts does not stall the loop. Their subsequent visual updates are already `idle_add`-dispatched — unchanged.

**Edit C — shutdown wiring:** call `shutdown_persist_writer()` from the existing project-close / window-shutdown lambda chain (`ui/window.py` — the same place `stop_watching()` is called at :589).

**Thread-safety notes for the audit:**
- `update_card` mutates `self._cards[card_id]` under `self._lock` (:978-979) before enqueueing; the writer reads only the queued dict snapshot copy — no shared mutable state crosses threads.
- `_persist_queue` is guarded by its own lock; the writer pops under the same lock.
- The writer is a daemon thread; a hung write cannot block shutdown beyond the 2 s join.

**Invariants:**
1. `update_card` returns in <5 ms regardless of feed size (it no longer touches disk).
2. Every enqueued update is applied exactly once per drain, in per-card last-write-wins order.
3. A failed or not-found write is logged, never raised into the UI.

### 2.2 Phase 2 — Append-only update journal + compaction

**2.2.1 `utils/feed_store.py` — journal primitives**

Add:

```python
JOURNAL_FILENAME = "feed-updates.jsonl"
JOURNAL_COMPACT_THRESHOLD = 500   # lines; compact when exceeded
```

```python
def _journal_path(project_path: str) -> str:
    return os.path.join(project_path, ".crabcakes", JOURNAL_FILENAME)


def append_card_update(project_path: str, card_id: str, updates: dict) -> bool:
    """Append one update record to the journal — O(1), no full-file rewrite.

    Record: {"card_id": str, "updates": dict, "ts": float}. Uses O_APPEND so
    concurrent writers cannot interleave within a line; a torn final line is
    tolerated by the replay reader (it stops at the first unparseable line).
    Returns True if the record was written.
    """
```

```python
def _replay_journal(project_path: str) -> dict[str, dict]:
    """Read the journal and fold it into {card_id: merged_updates}.

    Stops at the first unparseable line (torn tail after a crash) and logs a
    warning. Missing journal is not an error.
    """
```

```python
def compact_feed(project_path: str, window: int = FEED_WINDOW_DEFAULT) -> int:
    """Fold the journal into feed.json, apply the sliding window, truncate.

    Returns the number of cards pruned. Runs under the feed flock so a
    concurrent reader never sees a half-compacted state.
    """
```

**Edit A — `load_feed` (:124):** after parsing the snapshot, apply the journal overlay before returning:

```python
    cards = [...existing parse...]
    overlay = _replay_journal(project_path)
    if overlay:
        by_id = {c.card_id: c for c in cards if c.card_id}
        for card_id, updates in overlay.items():
            card = by_id.get(card_id)
            if card is None:
                continue          # pruned card — update is stale, drop it
            for key, val in updates.items():
                if key in {"accepted", "reviewed", "metadata"} and hasattr(card, key):
                    setattr(card, key, val)
    return cards
```

**Edit B — `update_feed_card` (:227):** keep the function for compatibility, but make it the *compaction-time* path. The hot path becomes `append_card_update` + threshold check:

```python
def update_feed_card(project_path, card_id, updates) -> bool:
    """Update one card. Appends to the journal (O(1)); compacts when the
    journal exceeds JOURNAL_COMPACT_THRESHOLD. Falls back to the legacy
    read-modify-write only if the journal is unusable."""
    ok = append_card_update(project_path, card_id, updates)
    if ok:
        if _journal_line_count(project_path) >= JOURNAL_COMPACT_THRESHOLD:
            compact_feed(project_path)
        return True
    return _update_feed_card_legacy(project_path, card_id, updates)
```

The legacy body is preserved verbatim as `_update_feed_card_legacy` — this keeps the 13 existing `test_feed_store.py` update tests meaningful (they assert observable behaviour, which is unchanged) and gives a rollback path.

**Edit C — `_atomic_write_json` (:30):** add a `compact: bool = True` parameter and stop using `indent=2` for the feed snapshot (measured: `indent=2` costs ~0.31 s and ~2× bytes on the real feed). Keep `indent=2` for `feed-prefs.json` (small, human-edited). `_atomic_write_json` currently hardcodes `indent=2` at :38.

**Edit D — bounded lock (new hazard from the 2026-09-11 capture):** `_acquire_lock` (:96-113) currently falls through to an **unbounded blocking** `fcntl.flock(fd, fcntl.LOCK_EX)` at :112 after 5 non-blocking retries. Give it a deadline:

```python
_LOCK_TIMEOUT_SEC = 2.0

def _acquire_lock(path: str, timeout: float = _LOCK_TIMEOUT_SEC) -> tuple | None:
    """Acquire the feed lock. Returns (fd, lock_path) or None on timeout.

    Never blocks unbounded: the final attempt still uses LOCK_NB inside a
    deadline loop. Callers must handle None (log + skip the write; the
    journal keeps the data safe for the next attempt).
    """
```

All callers (`load_feed`, `save_feed`, `append_feed_card`, `update_feed_card`, `compact_feed`) must handle the `None` return: read paths fall back to a lock-free read with a warning; write paths skip and log. Rationale: the capture caught the main thread parked in the unbounded fallback 9 times — on the main thread that is an unbounded UI stall, strictly worse than a slow parse. A held lock must never be able to freeze the UI.

**Invariants:**
1. `feed.json` alone remains a valid, complete feed for any reader that does not know about the journal (backward compatible), except for updates still pending in the journal.
2. A torn final journal line never loses a *previous* record.
3. Compaction is atomic: `feed.json` is replaced via `os.replace`, then the journal is truncated — readers between the two steps see either the old snapshot + full journal (correct after replay) or the new snapshot + full journal (replay is idempotent, so still correct).
4. Replay is idempotent: running it twice yields the same card state.

### 2.3 Phase 3 — Sliding-window pruning

**Edit A — `utils/feed_store.py`:** add the window constant and the retention rules:

```python
FEED_WINDOW_DEFAULT = 2000        # newest N cards retained in the snapshot
```

Retention rules inside `compact_feed` — a card is **pinned** (never pruned) if any of:

- `accepted is None` and `reviewed` is False and the card is inside the newest window — normal case;
- `accepted is not None` (an accepted/rejected decision already recorded — pruning it would orphan the decision and the `seq_num` narrative);
- `metadata.get("needs_review")` or `metadata.get("needs_approval")` (still actionable — `update_feed_card` would silently return False after pruning);
- `card_type == "git_commit"` (cheap, few, and referenced by review history).

Pruning drops the oldest non-pinned cards beyond the window. `seq_num` numbering is preserved: the highest `seq_num` seen is retained in a small `feed-meta.json` (`{"seq_floor": N}`) so new cards continue numbering even after the oldest are pruned.

**Edit B — `ui/handlers/feed_handler.py`:** `_load_and_render` (:1081) already pages rendering at `PAGE_SIZE = 15` with a "Load More" backlog (:1149-1151, :1178) — **no change needed**; the backlog simply becomes at most `FEED_WINDOW_DEFAULT` cards. Surface the pruning as a one-line feed system card when it happens (`"Feed compacted — {N} oldest cards archived"`), so nothing disappears silently.

**Edit C — stale-update tolerance:** `update_card` (:963) already returns early with a warning when `card_id not in self._cards` (:974-976); the Phase-1 writer logs not-found results. Confirm both paths stay non-raising.

**Invariants:**
1. No card that can still be acted on (pending accept/reject, needs-review, needs-approval) is ever pruned.
2. `seq_num` remains monotonic across compaction; no duplicate numbers.
3. Pruning is logged and surfaced, never silent.
4. A full feed load stays <100 ms at the window default on the real 9,500-card feed (verified by test).

### 2.4 Phase 4 — Deferred feed-card rendering (proposal Fix 4) + pre-loop batching (proposal Fix 6)

**Part A — `ui/handlers/feed_handler.py`:** add `update_card_in_place(card_id, card_data)` that mutates the status badge/body label by reference instead of rebuilding the whole card. `build_feed_card` (:747/:755/:869/:877) stays for creation; `update_card` uses the in-place path when the widget exposes the needed children, and falls back to the current rebuild otherwise.

Requires the card widget to expose references — either store them in `build_feed_card`'s returned widget as attributes (`widget._status_label`, `widget._body_label`) or query the widget tree once and cache. `feed_tab.replace_card` (:264) remains the fallback path.

**Part B — pre-loop work off the main thread (proposal Fix 6, carried here).** `send_to_special_agent` still performs several synchronous operations on the main thread before `send_message` spawns the loop thread: `rt.load_conversation(session_key)` (disk I/O + deserialization), `_rebuild_conversation_context` (the project-switch path, rare), and conversation state syncing (api_key, model, MCP server list, SI enforcement, step-count reset). Fix 1 already moved `build_system_prompt` into the loop thread via `defer_prompt_build`; Part B moves the remaining items.

Approach: extract the preparation block into a `_prepare_turn()` closure and run it on the background thread, with the main thread doing only (a) showing the "thinking" indicator and (b) starting the thread. Risk is MEDIUM-HIGH per the original proposal (§4.2 Fix 6) because those mutations currently rely on implicit main-thread serialization — the phase must verify under a lock that no concurrent reader (cancel, /clear, tab switch) can observe a half-prepared conversation, and must reuse the RACE-FIX v4 turn-token discipline for the dispatched callbacks.

**Note on priority:** the 09-11 profiler did not sample this path hot (it costs 300–500 ms once per *send*, not per tool result). It is carried here for completeness, not because it is currently the bottleneck.

**Part C — activity bubbles:** tool start/result emit `ActivityBubble`s (`agent_runtime_handler.py:1266`, `:1381`, `:1412`). Batch per-turn bubbles behind the same 250 ms cadence the status ticker already uses (`activity_handler.py:641`) rather than dispatching one per event.

### 2.5 Phase 5 — Git off the main thread

**Edit A — `ui/handlers/feed_handler.py:1619` (`on_filesystem_event`):** remove the inline `snapshot_from_git_diff` call. Create the card immediately with `conversation_snapshot=None`, and let the existing deferred path (`_finalize_snapshot`, :1623) fill it.

**Edit B — `_finalize_snapshot` (:1623) / `_maybe_create_snapshot` (:1657):** run the snapshot build on a worker thread (reuse the Phase-1 writer thread or a second small daemon), then dispatch only the widget update back via `GLib.idle_add`. The chat-box widget walk (`_extract_messages_from_chat_box`, :1706) is GTK-bound and must stay on the main thread — split it from the pure-Python snapshot construction (`snapshot_from_messages`, `conversation_store.py:33`, already pure and bounded by `MAX_SNAPSHOT_MESSAGES`).

**Edit C — debounce/coalesce:** multiple filesystem events for the same path on the same tick should produce at most one snapshot build. The existing 200 ms debounce (`crabwatch_handler.py:109`) stays; add last-write-wins per `(project, file_path)`.

### 2.6 Phase 6 — Per-session lock sharding (audit #4)

**Edit A — `agent/runtime.py:510`:** keep `self._lock` for process-wide state (`_conversations` map membership, `_running`, `_runtimes`), and add a per-session lock map:

```python
        self._session_locks: dict[str, threading.Lock] = {}
        self._session_locks_guard = threading.Lock()

    def _session_lock(self, session_key: str) -> threading.Lock:
        with self._session_locks_guard:
            lock = self._session_locks.get(session_key)
            if lock is None:
                lock = self._session_locks[session_key] = threading.Lock()
            return lock
```

**Edit B:** re-scope the ~21 `self._lock` uses (:510 verified) — anything that mutates or reads only one session's `Conversation` moves to that session's lock; anything touching the conversations dict itself stays on `self._lock`. The lock is **never held across a dispatch** (`_dispatch`, :573) — that rule already exists in the `_state_lock` narrative (:394-400) and must be extended to `_lock`.

**Edit C:** `_state_lock` (:533) is already separate and correctly scoped (**not** held during dispatch) — leave it. Document the three-lock discipline (global / per-session / turn-state) in the `__init__` docstring block (:384-405), which already documents two of them.

### 2.7 Phase 7 — Final-render spike + render pool (audit #6/#7)

**Edit A — `chat_render_handler.py:215`:** `_pool` is a class attribute — every handler instance shares two workers. Make it a per-instance pool bounded by an explicit constant, and shut it down with the handler.

**Edit B — `end_streaming` (:623):** keep the plain streaming bubble and upgrade formatting incrementally rather than one large main-thread stall: reuse the already-present 2-worker `render_async` path (`chat_render_handler.py:219`) for `process_segments`, and assemble in chunks. Success criterion: no single main-thread stall >100 ms when finalizing a long (10 k+ char) response.

### 2.8 Phase 8 — Spike only (no implementation in this spec)

The architectural item from `docs/audits/2026-09-01-core-loop-performance.md` #1 — moving the agent runtime/SSE parsing out of the GTK process (subprocess + IPC), or off pure-Python paths — is **not** implemented here. It is a genuine architecture change with a large blast radius (session lifecycle, callbacks, gateway, tests). It requires its own spike spec. This spec's Phase 8 deliverable is therefore: a written spike proposal under `docs/proposals/` that scopes the subprocess/IPC option, its risk surface, and a migration path — nothing more.

---

## 3. Data flow after Phase 1–3

```
Tool result arrives (runtime thread)
  → _on_tool_call_result → GLib.idle_add
    → _do_tool_call_result [main]
      → feed_handler.update_card [main]
        → mutate in-memory card + rebuild/patch widget   [main, ~ms]
        → _enqueue_card_update(...)                      [main, <1 ms, no disk]
  → writer thread [background]
    → feed_store.update_feed_card
      → append_card_update → O(1) journal line           [no full parse]
      → if journal >= 500 lines: compact_feed            [occasional]
         → fold journal into snapshot, apply window,
           write compact JSON atomically, truncate journal
```

`load_feed` = read snapshot + replay journal (both bounded by the window). Main-thread cost per tool call drops from ~620 ms to <5 ms.

---

## 4. Test plan

| Test | Phase | Asserts |
|---|---|---|
| `test_update_card_returns_immediately_on_large_feed` | 1 | `update_card` wall time <50 ms with a 9,500-card fixture |
| `test_enqueue_coalesces_repeated_updates` | 1 | N enqueues for one card → 1 writer call; final state = last update |
| `test_writer_survives_exception` | 1 | A `feed_store` raise does not kill the writer; subsequent updates persist |
| `test_append_card_update_is_o1` | 2 | Journal append time on a 9,500-card feed within 3× of an empty feed |
| `test_journal_replay_idempotent` | 2 | Replay twice → identical card state |
| `test_torn_journal_tail_is_tolerated` | 2 | Truncated final line → all prior records applied, one warning |
| `test_compact_folds_and_truncates` | 2 | Post-compaction `feed.json` contains the updates; journal empty |
| `test_prune_retains_actionable_cards` | 3 | pending/needs-review/needs-approval/git_commit cards survive pruning |
| `test_seq_num_monotonic_across_compaction` | 3 | Numbering continues from `seq_floor`; no duplicates |
| `test_load_feed_under_100ms_at_window` | 3 | Timing bound at `FEED_WINDOW_DEFAULT` |
| `test_finalize_snapshot_off_main_thread` | 5 | GTK calls happen only on the main thread; git runs on the worker |
| `test_session_locks_are_independent` | 6 | Two sessions' transitions do not serialize on one lock |
| `test_end_streaming_no_long_stall` | 7 | Long-response finalize produces no >100 ms main-thread stall |
| `test_acquire_lock_times_out` | 2 | A held lock causes `_acquire_lock` to return `None` within the timeout — never an unbounded block |

Existing behaviour that must not regress: the 13 tests in `tests/test_feed_store.py`, the `test_feed_handler.py` suite, and the full-suite failure baseline (the 40-failure set must be byte-identical pre/post — the AC3 discipline).

---

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Journal and snapshot diverge after a crash mid-compaction | MEDIUM | Compaction order: write new snapshot atomically → truncate journal. Replay is idempotent, so replaying an already-folded journal is harmless. Test `test_torn_journal_tail_is_tolerated`. |
| A pruned card is later updated → silent state loss | HIGH | Retention rules pin every actionable card (Phase 3), the writer logs not-found, and compaction emits a visible feed card. |
| Background writer races the project-close path | MEDIUM | `shutdown_persist_writer()` joins with a 2 s timeout; residual writes are logged and the journal keeps them safe. |
| Coalescing loses an intermediate state a future feature needs | LOW | Documented contract: only `body`/`metadata`/`accepted`/`reviewed` are persisted, and only the latest matters (same as today's writer). |
| Lock sharding introduces a deadlock | MEDIUM | Never hold a per-session lock across dispatch; acquire order is documented (global → session → state) and enforced by test. |
| Feed window default too small for a user's history | LOW | `FEED_WINDOW_DEFAULT` configurable per project; pruning is surfaced, not silent. |

---

## 6. Success criteria

- [ ] Main-thread cost per tool result <5 ms (was ~620 ms) on the real 13.9 MB feed
- [ ] During a full agent turn (8+ tool calls), the app remains interactive: tab switches <200 ms, no "not responding" dialog
- [ ] `feed.json` load <100 ms at the default window
- [ ] Journal append is O(1) — independent of feed size
- [ ] Zero silent data loss: every pruned card is logged and surfaced; every dropped update is logged
- [ ] All existing feed tests pass unchanged; full-suite failure set byte-identical to baseline
- [ ] Measured before/after evidence pasted for each phase (the AC3 red-first discipline)

---

## 7. Phase ordering and effort

| Phase | Change | Effort | Risk |
|---|---|---|---|
| 1 | Background + coalesced writes | 3–4 h | LOW |
| 2 | Journal append + compaction | 4–6 h | MEDIUM |
| 3 | Sliding-window pruning | 3–4 h | MEDIUM (data retention rules) |
| 4 | Deferred card render + bubble batching | 3–4 h | MEDIUM |
| 5 | Git off the main thread | 2–3 h | LOW |
| 6 | Per-session lock sharding | 4–6 h | MEDIUM |
| 7 | Final-render spike + pool scoping | 3–4 h | MEDIUM |
| 8 | Architectural spike write-up only | 2 h | LOW |

Phase 1 alone removes the dominant stall and is independently shippable — it should ship first and be measured in production before Phase 2 begins.

**Reordering after the 2026-09-11 capture (§0):** Phases 1–3 carry the entire measured cost. Phases 4–7 are hygiene — the profiler found no samples in the git path, the render path, or any other lock. Schedule them after Phase 3 ships and is verified in production; Phase 8 stays a write-up only.

---

## 8. Measurement plan (evidence required per phase)

1. **Before/after main-thread stall:** `python3 - <<'EOF'` timer around `update_card` with the real 9,500-card fixture; plus the live `/proc/<pid>/task/<tid>/stat` sampling used in the 2026-09-11 investigation (3 s windows, main-thread delta).
2. **Live attribution:** py-spy dump/flamegraph against the running app during a real agent turn (requires sudo — see §10).
3. **Feed sizes:** bytes and card count before/after compaction.
4. **Regression gate:** full-suite failure-set diff against the recorded baseline.

---

## 9. Out of scope / follow-on specs

Every item here is a deliberate drop with a stated reason (§0a is the full ledger) — none is silently omitted.

- **Architectural runtime offload (audit #1)** — separate spike spec (Phase 8 writes the proposal only).
- **`os.walk` in `agent/tools.py:479`** (audit #7a) — no samples in the 09-11 capture; fold into a future tool-layer perf pass.
- **`time.sleep(wait_s)` retry in `agent/llm/streaming.py`** (audit #7b) — blocks a worker thread, never the main thread; thread-pool waste only; no samples captured.
- **`ui/views/file_tree.py` thread-per-operation** (audit #7c) — 2391 lines; no samples in the 09-11 capture. Revisit only if the file tree is separately implicated.
- **GTK internals / widget-count reduction in the chat tab** — no accumulation cap currently exists; separate investigation if it proves material.

---

## 10. Open items requiring the PM

- **Live attribution run:** py-spy must attach to the running app as root:
  `sudo env "PATH=$PATH" /home/q/.local/bin/py-spy dump --pid <PID> --nonblocking`
  (and, for a flamegraph, `py-spy record -o /tmp/crabcakes-flame.svg --pid <PID> --duration 60`).
  Which of the paths above actually dominates will be confirmed from that capture before Phase 2 starts.

---

## 11. Sign-off

- [ ] PM approves phasing
- [ ] Phase 1 implemented + measured
- [ ] Remaining phases scheduled against the Phase 1 measurement
