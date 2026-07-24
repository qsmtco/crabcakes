"""Comprehensive adversarial probe of Phase 3 fixes."""
import sys
sys.path.insert(0, '.')

from agent.runtime import _validate_streamed_arguments
from agent.llm.extractors import extract_tool_calls

print("=" * 60)
print("PHASE 3 BUG #1 CLOSURE PROBES")
print("=" * 60)

# 1. The exact Phase 2 BUG #1 repro
emitted = {"id": "call_x", "function": {"name": "clear_cache", "arguments": ""}}
calls = extract_tool_calls({"choices": [{"message": {"tool_calls": [emitted]}}]}, "openai")
print(f"1. empty-args full pipeline: {calls}")
assert calls == [("call_x", "clear_cache", {})], f"FAIL: got {calls}"
print("   PASS — tool call preserved with empty args dict")

# 2. Missing key (regression check — both pre/post-fix behave same)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f"}}]}}]}, "openai")
print(f"2. missing key: {r}")
assert r == [("c0", "f", {})]
print("   PASS — default still applies to missing key")

# 3. arguments=None (newly handled post-fix)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f", "arguments": None}}]}}]}, "openai")
print(f"3. arguments=None: {r}")
assert r == [("c0", "f", {})]
print("   PASS — None now treated as missing (post-fix)")

# 4. Malformed JSON still skipped (regression check)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "bad", "function": {"name": "x", "arguments": "not-json"}}]}}]}, "openai")
print(f"4. malformed: {r}")
assert r == []
print("   PASS — malformed still skipped")

# 5. arguments=False (bool, falsy)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f", "arguments": False}}]}}]}, "openai")
print(f"5. arguments=False: {r}")
# pre-fix: func.get("arguments", "{}") returns False → not str → args = False or {} = {}
# post-fix: same path (False is truthy-falsy-handled in else branch identically)
assert r == [("c0", "f", {})], f"FAIL: got {r}"
print("   PASS — bool False handled correctly in else branch")

# 6. arguments=0 (int 0, falsy)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f", "arguments": 0}}]}}]}, "openai")
print(f"6. arguments=0: {r}")
assert r == [("c0", "f", {})]
print("   PASS — int 0 handled correctly in else branch")

# 7. arguments=dict (non-empty non-string, truthy)
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f", "arguments": {"k": "v"}}]}}]}, "openai")
print(f"7. arguments=dict: {r}")
assert r == [("c0", "f", {"k": "v"})]
print("   PASS — non-empty dict passes through")

# 8. arguments=list
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [{"id": "c0", "function": {"name": "f", "arguments": [1, 2]}}]}}]}, "openai")
print(f"8. arguments=list: {r}")
assert r == [("c0", "f", [1, 2])]
print("   PASS — list passes through")

# 9. Mixed: valid + empty + malformed
r = extract_tool_calls({"choices": [{"message": {"tool_calls": [
    {"id": "good", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}},
    {"id": "empty", "function": {"name": "clear_cache", "arguments": ""}},
    {"id": "bad", "function": {"name": "exec", "arguments": "{broken"}},
]}}]}, "openai")
print(f"9. mixed (valid+empty+malformed): {r}")
expected = [("good", "read_file", {"path": "x.py"}), ("empty", "clear_cache", {})]
assert r == expected, f"FAIL: expected {expected}, got {r}"
print("   PASS — valid and empty preserved, malformed skipped")

print()
print("=" * 60)
print("PHASE 3 BUG #2 CLOSURE PROBES")
print("=" * 60)

# 1. int (was crashing pre-fix)
r = _validate_streamed_arguments(42, "f", "sk")
print(f"1. int 42: {r}")
assert r is False
print("   PASS — returns False, no crash")

# 2. list
r = _validate_streamed_arguments([1, 2, 3], "f", "sk")
print(f"2. list: {r}")
assert r is False
print("   PASS — returns False, no crash")

# 3. dict
r = _validate_streamed_arguments({"a": 1}, "f", "sk")
print(f"3. dict: {r}")
assert r is False
print("   PASS — returns False, no crash")

# 4. bytes (json.loads accepts bytes, should return True)
r = _validate_streamed_arguments(b'{"x": 1}', "f", "sk")
print(f"4. bytes b'{{\"x\": 1}}': {r}")
assert r is True
print("   PASS — bytes returns True (json.loads accepts bytes)")

# 5. None (still treated as empty, returns True)
r = _validate_streamed_arguments(None, "f", "sk")
print(f"5. None: {r}")
assert r is True
print("   PASS — None treated as empty (returns True)")

# 6. Valid JSON (regression check)
r = _validate_streamed_arguments('{"x": 1}', "f", "sk")
print(f"6. valid JSON: {r}")
assert r is True
print("   PASS — valid JSON still returns True")

# 7. Empty string (regression check)
r = _validate_streamed_arguments("", "f", "sk")
print(f"7. empty string: {r}")
assert r is True
print("   PASS — empty string still returns True")

# 8. Malformed JSON (regression check)
r = _validate_streamed_arguments("{not-json", "f", "sk")
print(f"8. malformed JSON: {r}")
assert r is False
print("   PASS — malformed still returns False")

# 9. Float (non-int non-string)
r = _validate_streamed_arguments(3.14, "f", "sk")
print(f"9. float 3.14: {r}")
# json.loads(3.14) raises TypeError (not str/bytes/bytearray)
assert r is False
print("   PASS — float returns False via TypeError branch")

# 10. True/False (bool is int subclass)
r = _validate_streamed_arguments(True, "f", "sk")
print(f"10. True: {r}")
assert r is False
print("   PASS — bool returns False via TypeError branch")

print()
print("=" * 60)
print("ALL PROBES PASS — BUG #1 AND BUG #2 CLOSED")
print("=" * 60)
