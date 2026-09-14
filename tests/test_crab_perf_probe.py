# tests/test_crab_perf_probe.py
# Unit tests for scripts/crab_perf_probe.py — the pure logic ONLY
# (percentiles, mean/median/p90/max summary, budget decision, /proc stat
# parsing). Per delegation: NO 60 s soak runs in the test suite; the sampling
# loop is verified live by the §7 measurement runs, not here.
#
# The probe module is loaded by file path (scripts/ is not an importable
# package) — same pattern as tests/test_crab_status_cli.py.

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = PROJECT_ROOT / "scripts" / "crab_perf_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("crab_perf_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


# ── bucketing/threshold decision (the §7 gate logic) ─────────────────────────


def test_summarize_budget_decision():
    """The gate: 'sustained' = MEAN vs budget — over → exit 1 path, under → 0."""
    # Well under budget (healthy idle ~2-6 % per the spec baseline)
    report = probe.summarize([2.0, 3.0, 4.0, 5.0, 6.0], budget=10.0)
    assert report["mean"] == 4.0
    assert report["over_budget"] is False
    assert report["samples"] == 5

    # Over budget (the pinned state: ~100 % sustained)
    pinned = probe.summarize([99.8, 100.0, 100.0, 99.9], budget=10.0)
    assert pinned["over_budget"] is True
    assert pinned["mean"] > 99.0

    # Exactly at the budget is NOT over (the gate is strict >)
    at_budget = probe.summarize([10.0, 10.0], budget=10.0)
    assert at_budget["over_budget"] is False

    # A single spike must NOT fail the sustained gate (max is informational):
    # one 90 % window across ten keeps the mean at 9.9 < 10.
    spike = probe.summarize([1.0] * 9 + [90.0], budget=10.0)
    assert spike["over_budget"] is False
    assert spike["max"] == 90.0
    assert spike["mean"] == 9.9


def test_summarize_tail_stats():
    """median/p90/max are the §7 report fields — check the math exactly."""
    report = probe.summarize([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                              80.0, 90.0], budget=10.0)
    assert report["median"] == 45.0
    # nearest-rank p90 over 10 samples = ceil(0.9*10)-th = 9th = 80.0
    assert report["p90"] == 80.0
    assert report["max"] == 90.0


def test_percentile_nearest_rank():
    assert probe._percentile([], 90) == 0.0          # degenerate run prints 0s
    assert probe._percentile([5.0], 90) == 5.0
    assert probe._percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0   # ceil(2)-th
    assert probe._percentile([1.0, 2.0, 3.0, 4.0], 100) == 4.0  # max
    assert probe._percentile([1.0, 2.0, 3.0, 4.0], 25) == 1.0   # floor at 1


def test_cpu_percent_single_thread_ceiling():
    """One thread ≤ one core: ticks beyond wall×clk indicate mis-attribution
    and must never come out of this function as sane numbers for a tid."""
    clk = 100.0
    # 100 ticks over 1 s at 100 Hz = exactly one core = 100 %
    assert probe._cpu_percent(100, 1.0, clk) == 100.0
    # 250 ms of a 5 s window (the §7 window size)
    assert probe._cpu_percent(125, 5.0, clk) == 25.0
    # Degenerate walls guard against division by zero
    assert probe._cpu_percent(500, 0.0, clk) == 0.0
    assert probe._cpu_percent(500, 5.0, 0.0) == 0.0


def test_stat_ticks_parses_comm_with_parens_and_spaces(tmp_path):
    """utime/stime extraction must survive comm values containing ')' and
    spaces — naive .split() mis-indexes and would silently mis-measure."""
    fake = tmp_path / "stat"
    # comm = "main) thr" — contains both a ')' and a space
    fake.write_text(
        "4242 (main) thr) S 1 4242 4242 0 -1 4194560 100 0 0 0 "
        "1500 250 0 0 20 0 1 0 1000 1000000 1000 18446744073709551615\n")
    parsed = probe._stat_ticks(str(fake))
    assert parsed == (1500, 250), "utime=field14, stime=field15 after last ')'"

    # Unreadable / malformed → None (probe treats as process-gone)
    assert probe._stat_ticks(str(tmp_path / "missing")) is None
    bad = tmp_path / "bad"
    bad.write_text("no parens here")
    assert probe._stat_ticks(str(bad)) is None
