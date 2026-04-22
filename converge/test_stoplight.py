"""Tests for the standalone stoplight module."""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "..")

from stoplight import compute_convergence, should_stop, should_stop_legacy


def test_qac_rule_turn2():
    """Turn ≤ 2 always continues — QAC form."""
    r = [{"text": "hi"}, {"text": "hello"}]
    assert should_stop(r, 1) is False
    assert should_stop(r, 2) is False


def test_hard_wall_turn15():
    """Turn ≥ 15 always stops — hard wall."""
    r = [{"text": "x"}] * 15
    assert should_stop(r, 15) is True
    assert should_stop(r, 16) is True


def test_polite_stops_turn3():
    """Polite-only response at turn 3 triggers stop."""
    r = [
        {"text": "Here's the fix."},
        {"text": "Confirmed, looks good."},
        {"text": "Thanks!"},
    ]
    assert should_stop(r, 3) is True


def test_substantive_conversation():
    """Substantive multi-turn conversation defers to model."""
    r = [
        {"text": "What's the segfault?"},
        {"text": "Use-after-free in session cleanup."},
        {"text": "Got it."},
        {"text": "The fix looks correct, apply it and run tests."},
    ]
    result = compute_convergence(r)
    assert 0.0 <= result["prob_stop"] <= 1.0
    assert result["signal"] == "neutral"


def test_returns_valid_output():
    """compute_convergence returns a well-formed dict."""
    r = [{"text": "hello"}] * 5
    result = compute_convergence(r)
    assert "prob_stop" in result
    assert "signal" in result
    assert 0.0 <= result["prob_stop"] <= 1.0


def test_legacy_decision():
    """Legacy function returns a tuple[bool, str]."""
    r = [{"text": "done"}]
    stop, signal = should_stop_legacy(r)
    assert isinstance(stop, bool)
    assert isinstance(signal, str)
    assert signal.startswith(("convergence_detected", "active_discussion", "borderline"))


if __name__ == "__main__":
    test_qac_rule_turn2()
    test_hard_wall_turn15()
    test_polite_stops_turn3()
    test_substantive_conversation()
    test_returns_valid_output()
    test_legacy_decision()
    print("All tests passed.")
