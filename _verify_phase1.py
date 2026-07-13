"""Verification script for PHASE 1 — Agent-Issued /compact and /clear."""
import subprocess, sys

def run(cmd, label):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print(f"[PASS] {label}")
            print(f"       {r.stdout.strip()}")
        else:
            print(f"[FAIL] {label}")
            print(f"       {r.stderr.strip()}")
        return r.returncode == 0
    except Exception as e:
        print(f"[ERROR] {label}: {e}")
        return False

ok = True

ok &= run(
    'python3 -c "import ast; ast.parse(open(\'ui/handlers/agent_command_handler.py\').read()); print(\'SYNTAX OK\')"',
    "1. Syntax check"
)

ok &= run(
    "grep -c \"'compact'\" ui/handlers/agent_command_handler.py",
    "2. 'compact' in filters (expect line count)"
)

ok &= run(
    "grep -n \"Pass 6\\|compact|clear\" ui/handlers/agent_command_handler.py",
    "3. Pass 6 exists"
)

ok &= run(
    "grep -n \"_record_action_result\" ui/handlers/agent_command_handler.py",
    "4. _record_action_result exists"
)

ok &= run(
    'grep -n "response_text" ui/handlers/agent_command_handler.py | grep -v "def \\|return\\|#"',
    "5. response_text branch"
)

ok &= run(
    "python3 -m pytest tests/test_agent_command_handler.py -v -k 'CompactClear or compact_clear'",
    "6. New tests (by keyword)"
)

ok &= run(
    "python3 -m pytest tests/test_agent_command_handler.py -q --tb=short 2>&1 | tail -5",
    "7. All tests"
)

sys.exit(0 if ok else 1)
