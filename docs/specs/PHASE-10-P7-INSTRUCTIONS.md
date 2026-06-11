# PHASE 10 — P7: Migration script for existing providers.yaml

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Step 7 of the master spec's Implementation Order

---

## Files to change

1. `scripts/migrate_provider_caller.py` — NEW file, ~30 lines

## What to do

**Create a new file `scripts/migrate_provider_caller.py`:**

```python
#!/usr/bin/env python3
"""One-shot migration: populate the `caller` field in providers.yaml.

Reads ~/.config/crabcakes/providers.yaml, sets caller for each entry from
default_model.split("/")[0] if caller is empty, and writes back.

Idempotent: re-running on already-migrated files is a no-op.

Usage:
    python3 scripts/migrate_provider_caller.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils.providers_store import load_providers, save_providers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing")
    args = parser.parse_args()

    providers = load_providers()
    changed = 0
    for p in providers:
        if not p.caller and p.default_model and "/" in p.default_model:
            new_caller = p.default_model.split("/")[0]
            print(f"  {p.name}: caller '{p.caller}' -> '{new_caller}'")
            p.caller = new_caller
            changed += 1
        elif p.caller:
            print(f"  {p.name}: caller already set to '{p.caller}' (skipped)")

    if changed == 0:
        print("No migration needed.")
        return 0

    if args.dry_run:
        print(f"[dry-run] Would update {changed} provider(s).")
        return 0

    save_providers(providers)
    print(f"Migrated {changed} provider(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note:** The script intentionally mirrors the auto-detect logic in `SettingsHandler.add_or_update` (P5 followup). If the two ever diverge, update both. The script is a one-shot — once a user runs it (or opens Settings and saves), all entries have explicit `caller` values and the script becomes a no-op on re-run.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Do NOT import from `ui.*` or `agent.*` (this script must be runnable without GTK/agent imports)
- Do NOT add any new dependencies — use only stdlib + existing project imports
- The script must be **idempotent** (re-running is safe)
- The script must support `--dry-run` for safety
- Mirror the auto-detect logic from `SettingsHandler.add_or_update` exactly

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
test -f scripts/migrate_provider_caller.py && echo "EXISTS" || echo "MISSING"
wc -l scripts/migrate_provider_caller.py
# Expect: ~50 lines
```

```bash
cd /home/q/projects/crabcakes
python3 scripts/migrate_provider_caller.py --dry-run
```

Expect: shows each provider with the caller that would be set, or "already set" / "No migration needed".

```bash
cd /home/q/projects/crabcakes
# Verify idempotency: run --dry-run twice, expect same output
python3 scripts/migrate_provider_caller.py --dry-run > /tmp/run1.txt
python3 scripts/migrate_provider_caller.py --dry-run > /tmp/run2.txt
diff /tmp/run1.txt /tmp/run2.txt && echo "IDEMPOTENT" || echo "NOT IDEMPOTENT"
```

```bash
cd /home/q/projects/crabcakes
# Verify the script is executable
test -x scripts/migrate_provider_caller.py && echo "EXECUTABLE" || echo "NOT EXECUTABLE (may need chmod +x)"
```

## Report

- Files created with line count
- Full verification output
- The --dry-run output showing what would change
- Idempotency check result
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.