#!/usr/bin/env python3
"""
Generate synthetic crabcakes-style agent conversations via MiniMax API.

Creates labeled stop/continue conversations for training data expansion.
Saves batches to tests/fixtures/synthetic_v{N}.json

Usage:
    python3 generate_synthetic_conversations.py          # generate 1 batch (20)
    python3 generate_synthetic_conversations.py --count 50  # 50 examples
    python3 generate_synthetic_conversations.py --merge   # merge all into synthetic_merged.json
"""
import argparse
import json
import os
import re
import urllib.request
import sys

# ─── Config ──────────────────────────────────────────────────────────────────

DEFAULT_BATCH_SIZE = 20
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
MERGE_OUTPUT = os.path.join(OUTPUT_DIR, "synthetic_merged.json")

SYSTEM_PROMPT = """You are a data generator for training a conversation classifier.

Generate realistic multi-turn technical conversations between two AI agents (Agent A and Agent B).
Output ONLY valid JSON array. No markdown, no explanation.

Schema per conversation:
{
  "conversation": [{"speaker": "A" | "B", "text": "..."}],
  "label": "stop" | "continue",
  "reason": "one sentence"
}

stop examples: resolved Q&A with confirmation, polite close after fix
continue examples: open follow-up, new angle introduced, ongoing investigation

Topics: debugging, code review, architecture, API design, deployment, testing."""

USER_PROMPT_TEMPLATE = """Generate exactly {count} diverse technical conversations.
Mix of stop and continue. Output JSON array only."""

# ─── API ──────────────────────────────────────────────────────────────────────

def load_api_key():
    try:
        with open(os.path.expanduser("~/.config/crabcakes/config.json")) as f:
            return json.load(f).get("apiKey", "")
    except Exception:
        return ""


def _call_minimax(prompt: str, api_key: str) -> str:
    payload = json.dumps({
        "model": "MiniMax-M2.5-Lightning",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 3000,
    }).encode()
    req = urllib.request.Request(
        "https://api.minimax.io/v1/text/chatcompletion_v2",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def _parse_json(raw: str) -> list[dict]:
    # Strip markdown
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("[") or p.startswith("{"):
                raw = p
                break

    # Try direct parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Try extract array
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start:end])
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # Regex extract individual objects
    pattern = r'\{[^{}]*(?:"conversation"[^{}]*|"label"[^{}]*)\}'
    matches = re.findall(pattern, raw, re.DOTALL)
    results = []
    for m in matches:
        try:
            obj = json.loads(m)
            if isinstance(obj, dict) and "conversation" in obj and "label" in obj:
                results.append(obj)
        except Exception:
            pass
    return results


def generate_batch(n: int, api_key: str) -> list[dict]:
    """Generate in sub-batches of 5 to avoid token limits."""
    all_results = []
    sub = 5
    for _ in range(0, n, sub):
        actual = min(sub, n - len(all_results))
        prompt = USER_PROMPT_TEMPLATE.format(count=actual)
        raw = _call_minimax(prompt, api_key)
        parsed = _parse_json(raw)
        all_results.extend(parsed)
        print(f"  sub-batch: {len(parsed)} parsed, running total: {len(all_results)}", file=sys.stderr)
    return all_results


# ─── File ops ────────────────────────────────────────────────────────────────

def next_batch_number() -> int:
    nums = []
    for f in os.listdir(OUTPUT_DIR):
        m = re.match(r"^synthetic_v(\d+)\.json$", f)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def save_batch(conversations: list[dict], batch_num: int) -> str:
    path = os.path.join(OUTPUT_DIR, f"synthetic_v{batch_num}.json")
    with open(path, "w") as f:
        json.dump(conversations, f, indent=2)
    return path


def merge_all() -> tuple[str, int]:
    all_conv = []
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if re.match(r"^synthetic_v\d+\.json$", f):
            with open(os.path.join(OUTPUT_DIR, f)) as fh:
                all_conv.extend(json.load(fh))
    with open(MERGE_OUTPUT, "w") as f:
        json.dump(all_conv, f, indent=2)
    return MERGE_OUTPUT, len(all_conv)


# ─── Validate ────────────────────────────────────────────────────────────────

def validate(conversations: list[dict]) -> list[dict]:
    valid = []
    for c in conversations:
        conv = c.get("conversation", [])
        if not isinstance(conv, list) or len(conv) < 2:
            continue
        if c.get("label") not in ("stop", "continue"):
            continue
        valid.append({"conversation": conv, "label": c["label"], "reason": c.get("reason", "")})
    return valid


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    if args.merge:
        path, total = merge_all()
        print(f"Merged {total} conversations → {path}")
        return

    api_key = load_api_key()
    if not api_key:
        print("ERROR: No apiKey in ~/.config/crabcakes/config.json", file=sys.stderr)
        sys.exit(1)

    print(f"Generating {args.count} conversations...", file=sys.stderr, flush=True)
    raw = generate_batch(args.count, api_key)
    valid = validate(raw)
    print(f"  {len(raw)} raw → {len(valid)} valid", file=sys.stderr)

    if not valid:
        print("ERROR: No valid conversations generated.", file=sys.stderr)
        sys.exit(1)

    n = next_batch_number()
    path = save_batch(valid, n)
    print(f"Saved v{n} ({len(valid)} examples) → {path}")


if __name__ == "__main__":
    main()
