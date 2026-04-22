#!/usr/bin/env python3
import sys
sys.path.insert(0, "..")
from stoplight import compute_convergence, should_stop, should_stop_legacy

test_qac_rule_turn2()
test_hard_wall_turn15()
test_polite_stops_turn3()
test_substantive_conversation()
test_returns_valid_output()
test_legacy_decision()
print("All tests passed.")

def test_qac_rule_turn2():
    r = [{"text": "hi"}, {"text": "hello"}]
    assert should_stop(r, 1) is False
    assert should_stop(r, 2) is False
    print("PASS: QAC rule turn 2")

def test_hard_wall_turn15():
    r = [{"text": "x"}] * 15
    assert should_stop(r, 15) is True
    assert should_stop(r, 16) is True
    print("PASS: hard wall turn 15+")

def test_polite_stops_turn3():
    r = [{"text": "Here's the fix."}, {"text": "Confirmed, looks good."}, {"text": "Thanks!"}]
    assert should_stop(r, 3) is True
    print("PASS: polite stops at turn 3")

def test_substantive_conversation():
    r = [{"text": "What's the segfault?"}, {"text": "Use-after-free in session cleanup."}, {"text": "Got it."}, {"text": "The fix looks correct, apply it and run tests."}]
    result = compute_convergence(r)
    assert 0.0 <= result["prob_stop"] <= 1.0
    assert result["signal"] == "neutral"
    print("PASS: substantive conversation")

def test_returns_valid_output():
    r = [{"text": "hello"}] * 5
    result = compute_convergence(r)
    assert "prob_stop" in result
    assert "signal" in result
    assert 0.0 <= result["prob_stop"] <= 1.0
    print("PASS: valid output")

def test_legacy_decision():
    r = [{"text": "done"}]
    stop, signal = should_stop_legacy(r)
    assert isinstance(stop, bool)
    assert isinstance(signal, str)
    print("PASS: legacy decision")
