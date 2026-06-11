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
