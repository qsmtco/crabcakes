#!/usr/bin/env python3
"""crab_perf_probe.py — main-thread CPU sampler for the UIRESP3 §7 gate.

⚠️  MAIN-THREAD ATTRIBUTION — READ BEFORE "SIMPLIFYING" ⚠️
This probe samples ``/proc/<pid>/task/<tid>/stat`` with ``tid == pid``.
Do NOT swap this for ``/proc/<pid>/stat``: that file is **process-wide**
(sums every thread), and using it produced a real mis-measurement during the
UIRESP3 investigation — the number was labelled "main thread" and read
100–124 % while the actual main thread sat at ~3 %. A single thread can
occupy at most one core, so any sustained reading above ~100 % from this
probe means the sampler is mis-attributing (check the tid).

⚠️  PRECONDITION for ``tid == pid`` (true today, NOT a universal invariant):
the GTK main loop runs on the Python main thread only because ``main.py``
calls ``Gtk.Application().run()`` from the ``__main__`` block. If ``app.run``
is ever moved onto a worker thread, ``tid == pid`` will silently sample the
WRONG thread (which idles near 0 % — the exact reading that would mask a real
regression). Re-verify before relying on this probe after any change to the
app's startup path; to find the real main thread, scan ``/proc/<pid>/task/*``
for the thread running the GLib main loop (``comm`` often ``gmain``) that is
R-state across the majority of samples.

Method (SPEC-UI-RESPONSIVENESS-3 §7 DISCOVERY notes): repeated 5 s windows;
per window, ``(utime+stime) delta ÷ (wall seconds × CLK_TCK) × 100``. The
report is mean / median / p90 / max over the full window plus feed-card
arrivals, so idle and storm conditions are distinguishable.

Budget (§7): the mean is the "sustained" figure — over budget when
``mean > --budget`` (default 10 %, the idle gate; use 25 for a storm run).

Read-only: /proc reads plus one optional feed.json read. Writes nothing.
Headless: no GTK anywhere.

Exit codes: 0 under budget · 1 OVER budget · 2 usage error · 3 process
vanished / never found.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

DEFAULT_DURATION = 60.0
DEFAULT_WINDOW = 5.0          # §7 reference method: 5 s windows
DEFAULT_BUDGET = 10.0         # §7 idle gate; pass 25 for a storm run

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE = 2
EXIT_PROC_GONE = 3


def _clk_tck() -> float:
    """Jiffies per second (usually 100). Falls back to 100 if unreadable."""
    try:
        value = os.sysconf("SC_CLK_TCK")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    except (ValueError, OSError, AttributeError):
        pass
    return 100.0


def _stat_ticks(path: str):
    """(utime, stime) from a /proc/*/stat file, or None if unreadable.

    comm (field 2) may contain spaces and parentheses — split on the LAST
    ')' and index the remainder from field 3 onward (audit-proof parsing;
    naive .split() breaks on comm like ``ma)in``).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, ValueError):
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    rest = text[close + 1:].split()
    # rest[0] is field 3 (state); utime is field 14 → rest[11],
    # stime is field 15 → rest[12].
    if len(rest) < 13:
        return None
    try:
        return int(rest[11]), int(rest[12])
    except ValueError:
        return None


def _cpu_percent(delta_ticks: float, wall_seconds: float, clk_tck: float) -> float:
    """Window CPU percentage for ONE thread (ceiling ~100 %).

    A thread runs on at most one core at a time, so ticks can never exceed
    wall_seconds × clk_tck for a single tid.
    """
    if wall_seconds <= 0 or clk_tck <= 0:
        return 0.0
    return (delta_ticks / (wall_seconds * clk_tck)) * 100.0


def _percentile(sorted_values, pct: float) -> float:
    """Nearest-rank percentile of an ascending list.

    ``_percentile([0..9], 90) == 8.0`` (ceil(0.9·10)-th value). Empty input
    returns 0.0 so a degenerate probe run still prints a report.
    """
    if not sorted_values:
        return 0.0
    import math
    rank = max(1, math.ceil((pct / 100.0) * len(sorted_values)))
    return float(sorted_values[rank - 1])


def summarize(samples, budget: float) -> dict:
    """The report block: mean/median/p90/max + the budget decision.

    "Sustained over 60 s" (§7) is judged on the MEAN; the tail stats are
    informational (a single GC pause should not fail the gate, but a high
    p90 with a low mean means bursty render work worth looking at).
    """
    ordered = sorted(float(s) for s in samples)
    mean = statistics.fmean(ordered) if ordered else 0.0
    median = statistics.median(ordered) if ordered else 0.0
    p90 = _percentile(ordered, 90)
    peak = ordered[-1] if ordered else 0.0
    return {
        "samples": len(ordered),
        "mean": round(mean, 2),
        "median": round(float(median), 2),
        "p90": round(p90, 2),
        "max": round(peak, 2),
        "budget": budget,
        "over_budget": mean > budget,
    }


def _count_cards(path):
    """Feed-card count from a feed.json (list shape or {"cards": [...]}}.

    Returns None when the file is missing/unreadable/unparseable — the probe
    still reports CPU; arrivals just read ``n/a``.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        cards = data.get("cards")
        if isinstance(cards, list):
            return len(cards)
    return None


def _feed_path_for(pid: int):
    """Best-effort feed.json for the app's active project (read-only).

    Reads /proc/<pid>/cwd and checks <cwd>/.crabcakes/feed.json. Returns None
    when absent — arrivals are optional colour, never a hard dependency.
    """
    try:
        cwd = os.path.realpath(f"/proc/{pid}/cwd")
    except OSError:
        return None
    candidate = os.path.join(cwd, ".crabcakes", "feed.json")
    return candidate if os.path.isfile(candidate) else None


def _run_probe(pid: int, duration: float, window: float, budget: float,
               feed_path, out=sys.stdout, sleep=time.sleep,
               monotonic=time.monotonic) -> int:
    """The sampling loop. Returns the process exit code."""
    # MAINTAINER: tid == pid only holds while Gtk.Application().run() executes
    # on the Python main thread (main.py's __main__ block). Re-verify this
    # assumption if the app's startup path changes — see the module docstring's
    # PRECONDITION note; a wrong tid reads ~0% and would mask a real pin.
    stat_path = f"/proc/{pid}/task/{pid}/stat"
    first = _stat_ticks(stat_path)
    if first is None:
        print(f"crab_perf_probe: cannot read main thread ({stat_path}) — "
              "is the process running? (main thread tid == pid)", file=sys.stderr)
        return EXIT_PROC_GONE

    clk = _clk_tck()
    cards_start = _count_cards(feed_path) if feed_path else None
    deadline = monotonic() + duration
    samples = []
    while True:
        window_start = monotonic()
        sleep(window)
        wall = monotonic() - window_start
        now = monotonic()
        before = _stat_ticks(stat_path)
        if before is None:
            print("crab_perf_probe: process vanished mid-probe", file=sys.stderr)
            return EXIT_PROC_GONE
        # Recompute the delta against the LAST snapshot, not the window start,
        # so sleep jitter is absorbed into wall (never into ticks).
        after = before
        delta = (after[0] - first[0]) + (after[1] - first[1])
        samples.append(_cpu_percent(delta, wall, clk))
        first = after
        if now >= deadline:
            break

    cards_end = _count_cards(feed_path) if feed_path else None
    report = summarize(samples, budget)
    arrivals = (None if cards_start is None or cards_end is None
                else max(0, cards_end - cards_start))

    print(f"crab_perf_probe: pid={pid} tid={pid} (main thread) "
          f"duration={duration:.0f}s window={window:.0f}s clk={clk:.0f}")
    print(f"  main-thread CPU: mean={report['mean']}% median={report['median']}% "
          f"p90={report['p90']}% max={report['max']}%  ({report['samples']} windows)")
    print(f"  feed card arrivals: "
          f"{'n/a (feed.json not found)' if arrivals is None else arrivals}")
    verdict = "OVER BUDGET" if report["over_budget"] else "within budget"
    print(f"  budget: mean <= {budget}% → {verdict}")
    return EXIT_OVER_BUDGET if report["over_budget"] else EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="crab_perf_probe.py",
        description="Main-thread CPU sampler for the UIRESP3 §7 gate "
                    "(per-thread /proc/<pid>/task/<tid>/stat — NOT /proc/<pid>/stat).")
    parser.add_argument("--pid", type=int, required=True, metavar="PID",
                        help="app PID to sample (its main thread tid == pid)")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        metavar="SECONDS", help=f"total sampling window "
                        f"(default {DEFAULT_DURATION:.0f}s — the §7 gate window)")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW,
                        metavar="SECONDS",
                        help=f"per-sample window (default {DEFAULT_WINDOW:.0f}s)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                        metavar="PCT",
                        help="mean CPU budget for the exit decision "
                             f"(default {DEFAULT_BUDGET:g}; use 25 for storm runs)")
    parser.add_argument("--feed-json", default=None, metavar="PATH",
                        help="feed.json to count card arrivals from "
                             "(default: <pid cwd>/.crabcakes/feed.json)")
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.window <= 0 or args.window > args.duration:
        parser.error("--duration/--window must be positive, window <= duration")
        return EXIT_USAGE
    if args.budget <= 0:
        parser.error("--budget must be positive")
        return EXIT_USAGE

    feed_path = args.feed_json or _feed_path_for(args.pid)
    return _run_probe(args.pid, args.duration, args.window, args.budget,
                      feed_path)


if __name__ == "__main__":
    sys.exit(main())
