#!/usr/bin/env python3
"""crab_mem_probe.py — RSS/VmData slope sampler for the SPEC-MEMORY-WIDGET-RATCHET gate.

⚠️  ARRIVAL METRIC — READ BEFORE "SIMPLIFYING" ⚠️
Do NOT measure card arrivals with the feed.json file length or the journal line
count. ``utils/feed_store.py`` folds the journal into the snapshot and then
TRUNCATES it (``JOURNAL_COMPACT_THRESHOLD = 500`` at ``utils/feed_store.py:55``,
truncated at ``:700-701``), so the line count sawtooths 0..500 and would report
near-zero arrivals for a busy feed. Use the delta of the **maximum ``seq_num``**
across cards instead: it is monotonic because ``_apply_overlay`` drops records
for absent cards rather than creating them, pruning removes from the OLDEST end,
and the load path back-fills missing ``seq_num`` (``models/feed_card.py:108``,
``ui/handlers/feed_handler.py:1608-1610``).

⚠️  VmData is NOT a memory-growth figure on its own. ``VmData`` is the size of
private writable mappings; it neither tracks resident pages nor shrinks when GTK
frees a widget. It is reported alongside ``VmRSS`` as a second axis, and the
BUDGET DECISION IS MADE ON THE ``VmRSS`` SLOPE — the axis every measurement in
the spec's DISCOVERY block uses (897 MB → 2,177 MB over ~7 h).

Method: sample ``/proc/<pid>/status`` every ``--interval`` s (default 10 s), then
report the least-squares mean slope in **MB/min** for each axis. Least squares
rather than (last - first) / minutes so a single outlier sample cannot dominate
the figure; with a flat series the two agree.

Read-only: /proc reads plus optional feed.json / journal reads. Writes nothing.
Headless: stdlib only — no PyGObject, no third-party deps, runnable with
``/usr/bin/python3``. Import-safe: no side effects at import time.

Exit codes: 0 under budget · 1 OVER budget · 2 usage error · 3 process vanished
/ never found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

DEFAULT_DURATION = 1800.0     # spec §2.5: default measurement window (30 min)
DEFAULT_INTERVAL = 10.0       # spec §2.5: /proc sample cadence
DEFAULT_BUDGET = 0.5          # MB/min of VmRSS — the spec §6 secondary gate
KB_PER_MB = 1024.0
SECONDS_PER_MINUTE = 60.0

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE = 2
EXIT_PROC_GONE = 3


def _read_status(pid: int):
    """{'VmRSS': kB, 'VmData': kB} from /proc/<pid>/status, or None.

    None means the process is gone / the file is unreadable — callers turn that
    into EXIT_PROC_GONE. ``VmRSS`` is required; ``VmData`` is included only when
    the kernel reports it (both are present on every Linux build we target, but
    the probe must not crash on a stripped /proc).
    """
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8",
                  errors="replace") as fh:
            text = fh.read()
    except (OSError, ValueError):
        return None
    values = {}
    for line in text.splitlines():
        if line.startswith("VmRSS:") or line.startswith("VmData:"):
            key, _, rest = line.partition(":")
            parts = rest.split()
            if not parts:
                continue
            try:
                values[key] = float(parts[0])
            except ValueError:
                continue
    if "VmRSS" not in values:
        return None
    return values


def _slope_mb_per_min(times, values) -> float:
    """Least-squares slope of `values` (kB) against `times` (s), in MB/min.

    Fewer than two points, or a degenerate time axis, returns 0.0 so a run
    shorter than one interval still prints a report instead of raising.
    """
    if len(times) < 2 or len(times) != len(values):
        return 0.0
    count = float(len(times))
    t_bar = sum(times) / count
    v_bar = sum(values) / count
    denom = sum((t - t_bar) ** 2 for t in times)
    if denom <= 0:
        return 0.0
    numer = sum((t - t_bar) * (v - v_bar) for t, v in zip(times, values))
    return (numer / denom) * SECONDS_PER_MINUTE / KB_PER_MB


def _slope_for(samples, times, field: str) -> float:
    """`_slope_mb_per_min` over the samples that actually carry `field`."""
    paired = [(t, s[field]) for t, s in zip(times, samples) if field in s]
    return _slope_mb_per_min([t for t, _ in paired], [v for _, v in paired])


def _cards_from(path):
    """The card list from a feed.json (list shape or {"cards": [...]}), or None."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        cards = data.get("cards")
        if isinstance(cards, list):
            return cards
    return None


def _max_seq_num(path):
    """Highest card ``seq_num`` in a feed.json, or None when unavailable.

    None means "no signal" (missing / unreadable / unparseable / no card carries
    a seq_num) — the probe still reports memory; arrivals read ``n/a``. A card
    with ``seq_num = None`` is skipped rather than coerced to 0: treating a
    missing number as the oldest possible sequence would make the maximum
    depend on which cards happen to be present.
    """
    cards = _cards_from(path)
    if cards is None:
        return None
    seqs = [
        c.get("seq_num") for c in cards
        if isinstance(c, dict) and isinstance(c.get("seq_num"), int)
    ]
    return max(seqs) if seqs else None


def _journal_lines(path) -> int:
    """Line count of the feed journal, or 0 when missing/unreadable.

    Only used for the SECONDARY signal (``len(cards) + journal lines``). That
    sum is NOT monotonic: every compaction fold moves journal lines into the
    snapshot and truncates the journal, so the sum sawtooths DOWN by
    len(folded) at each fold. Trend-colour only — max seq_num (see
    _max_seq_num) is the monotonic axis. Never used alone.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except (OSError, ValueError):
        return 0


def _feed_paths_for(pid: int):
    """Best-effort (feed.json, journal) for the app's active project.

    Reads /proc/<pid>/cwd and checks <cwd>/.crabcakes/. Returns None for a path
    that is absent — arrivals are optional colour, never a hard dependency.
    """
    try:
        cwd = os.path.realpath(f"/proc/{pid}/cwd")
    except OSError:
        return None, None
    base = os.path.join(cwd, ".crabcakes")
    feed = os.path.join(base, "feed.json")
    journal = os.path.join(base, "feed-updates.jsonl")
    return (feed if os.path.isfile(feed) else None,
            journal if os.path.isfile(journal) else None)


def _arrival_snapshot(feed_path, journal_path):
    """(max_seq, feed_cards + journal_lines) — either element may be None.

    The second element is None when no journal was readable, so the report can
    label it honestly rather than implying a journal term that was never read.
    """
    max_seq = _max_seq_num(feed_path) if feed_path else None
    total = None
    if feed_path:
        cards = _cards_from(feed_path)
        if cards is not None and journal_path:
            total = len(cards) + _journal_lines(journal_path)
    return max_seq, total


def _mb(kb: float) -> float:
    return kb / KB_PER_MB


def _run_probe(pid: int, duration: float, interval: float, budget: float,
               feed_path, journal_path, out=sys.stdout, sleep=time.sleep,
               monotonic=time.monotonic) -> int:
    """The sampling loop. Returns the process exit code.

    `out`/`sleep`/`monotonic` are injection seams for tests: the report goes to
    `out` (not a hard-wired sys.stdout) and the clock/sleep are replaceable, so a
    test can drive a full run with zero real waiting. Kept consistent with
    `crab_perf_probe._run_probe`'s signature.
    """
    start = monotonic()
    deadline = start + duration
    seq_start, total_start = _arrival_snapshot(feed_path, journal_path)

    times, samples = [], []
    first_read = True
    while True:
        now = monotonic()
        status = _read_status(pid)
        if status is None:
            if first_read:
                print(f"crab_mem_probe: cannot read /proc/{pid}/status — "
                      "is the process running?", file=sys.stderr)
            else:
                print("crab_mem_probe: process vanished mid-probe", file=sys.stderr)
            return EXIT_PROC_GONE
        first_read = False
        times.append(now - start)
        samples.append(status)
        if now >= deadline:
            break
        sleep(min(interval, max(0.0, deadline - monotonic())))

    rss_slope = _slope_for(samples, times, "VmRSS")
    vdata_slope = _slope_for(samples, times, "VmData")
    rss = [s["VmRSS"] for s in samples]
    vdata = [s["VmData"] for s in samples if "VmData" in s]
    seq_end, total_end = _arrival_snapshot(feed_path, journal_path)
    elapsed = times[-1] if times else 0.0

    print(f"crab_mem_probe: pid={pid} duration={duration:.0f}s "
          f"interval={interval:.0f}s samples={len(samples)}", file=out)
    print(f"  VmRSS:  mean slope={rss_slope:.2f} MB/min "
          f"(first={_mb(rss[0]):.1f} MB last={_mb(rss[-1]):.1f} MB)", file=out)
    if vdata:
        print(f"  VmData: mean slope={vdata_slope:.2f} MB/min "
              f"(first={_mb(vdata[0]):.1f} MB last={_mb(vdata[-1]):.1f} MB) "
              "[informational — not the gate]", file=out)
    else:
        print("  VmData: n/a (not reported by this kernel)", file=out)

    if seq_start is None or seq_end is None:
        print("  card arrivals: n/a (feed.json not found or has no seq_num)",
              file=out)
    else:
        arrivals = seq_end - seq_start
        rate = arrivals / (elapsed / SECONDS_PER_MINUTE) if elapsed > 0 else 0.0
        note = "  [negative: feed replaced or pruned mid-probe]" if arrivals < 0 else ""
        print(f"  card arrivals: {arrivals} over {elapsed:.0f}s "
              f"({rate:.2f} cards/min) [max seq_num delta]{note}", file=out)
    if total_start is not None and total_end is not None:
        print(f"  secondary signal: len(cards)+journal lines "
              f"{total_start} → {total_end} (delta {total_end - total_start})",
              file=out)

    over_budget = rss_slope > budget
    verdict = "OVER BUDGET" if over_budget else "within budget"
    print(f"  budget: VmRSS slope <= {budget:g} MB/min → {verdict}", file=out)
    return EXIT_OVER_BUDGET if over_budget else EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="crab_mem_probe.py",
        description="RSS/VmData slope sampler for the SPEC-MEMORY-WIDGET-RATCHET "
                    "§6 gate (mean slope in MB/min from /proc/<pid>/status).")
    parser.add_argument("--pid", type=int, required=True, metavar="PID",
                        help="app PID to sample")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        metavar="SECONDS",
                        help=f"total sampling window (default "
                             f"{DEFAULT_DURATION:.0f}s — the §6 window; the spec's "
                             f"precondition asks for >= 60 min on a fresh feed)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        metavar="SECONDS",
                        help=f"per-sample cadence (default {DEFAULT_INTERVAL:.0f}s)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                        metavar="MB_PER_MIN",
                        help="VmRSS slope budget for the exit decision "
                             f"(default {DEFAULT_BUDGET:g} MB/min)")
    parser.add_argument("--feed-json", default=None, metavar="PATH",
                        help="feed.json to read card arrivals from "
                             "(default: <pid cwd>/.crabcakes/feed.json)")
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.interval <= 0:
        parser.error("--duration/--interval must be positive")
        return EXIT_USAGE
    if args.budget <= 0:
        parser.error("--budget must be positive")
        return EXIT_USAGE

    if args.feed_json:
        feed_path = args.feed_json
        # Derive the journal from the same directory so the secondary signal
        # still works for an explicit --feed-json (it lives beside feed.json in
        # <project>/.crabcakes/). Missing sibling → secondary signal is skipped.
        sibling = os.path.join(os.path.dirname(os.path.abspath(feed_path)),
                               "feed-updates.jsonl")
        journal_path = sibling if os.path.isfile(sibling) else None
    else:
        feed_path, journal_path = _feed_paths_for(args.pid)
    return _run_probe(args.pid, args.duration, args.interval, args.budget,
                      feed_path, journal_path)


if __name__ == "__main__":
    sys.exit(main())
