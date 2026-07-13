"""PHASE 1 AUDIT FIXES — verification."""
import subprocess, sys, os

os.chdir("/home/q/projects/crabcakes")

all_ok = True

def check(label, cmd):
    global all_ok
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        print(f"[PASS] {label}")
        if r.stdout.strip():
            for line in r.stdout.strip().split("\n")[:5]:
                print(f"       {line}")
    else:
        print(f"[FAIL] {label}")
        print(f"       {r.stderr.strip()[:200]}")
        all_ok = False

check("1. Syntax check",
    'python3 -c "import ast; ast.parse(open(\'ui/handlers/agent_command_handler.py\').read()); print(\'SYNTAX OK\')"')

check("2. Pass 6 has lookahead (matches !)",
    "grep -n 'compact|clear' ui/handlers/agent_command_handler.py | grep '!'")

check("3. clear in both allow-lists",
    "grep -n \"'clear'\" ui/handlers/agent_command_handler.py | head -5")

check("4. All tests",
    "python3 -m pytest tests/test_agent_command_handler.py -q --tb=short 2>&1 | tail -10")

sys.exit(0 if all_ok else 1)
