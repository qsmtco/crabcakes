#!/usr/bin/env python3
"""
bulk_repair_empty_assistant.py — Repair corrupt empty-content assistant messages
across all crabcakes conversation files.

A corrupt message is: role == 'assistant' AND content == '' AND tool_calls == [].
These cause HTTP 400 errors from Cohere (and likely other strict providers) at
the next LLM call. The read-side filter in models/conversation.py:to_api_messages
substitutes a placeholder at serialization time, but the underlying file is still
corrupt. This script repairs the files directly.

Usage:
    python3 scripts/bulk_repair_empty_assistant.py --dry-run
    python3 scripts/bulk_repair_empty_assistant.py --apply --backup-dir PATH

Default conversations dir: ~/.config/crabcakes/conversations/
Default backup dir:         ~/.config/crabcakes/conversations/.bulk-repair-2026-07-05/

Idempotent: safe to re-run. Files with no corrupt messages are skipped entirely.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PLACEHOLDER = '[assistant returned no content — placeholder]'
CONV_DIR = Path.home() / '.config/crabcakes/conversations'


def is_corrupt(msg: dict) -> bool:
    """True if msg is an assistant message with empty content and no tool_calls."""
    return (
        msg.get('role') == 'assistant'
        and not msg.get('content', '')
        and not msg.get('tool_calls', [])
    )


def find_corrupt_indices(messages: list) -> list[int]:
    return [i for i, m in enumerate(messages) if is_corrupt(m)]


def repair_file(path: Path, backup_dir: Path, apply: bool) -> tuple[int, str]:
    """Returns (count_repaired, action). Action is 'repaired', 'skipped', 'error'."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return (0, f'error: {type(e).__name__}: {e}')

    # Accept both 'messages' key (Conversation.save format) and root-list format
    if isinstance(data, dict):
        messages = data.get('messages', [])
        is_wrapped = True
    elif isinstance(data, list):
        messages = data
        is_wrapped = False
    else:
        return (0, f'error: unexpected root type {type(data).__name__}')

    corrupt_indices = find_corrupt_indices(messages)
    if not corrupt_indices:
        return (0, 'skipped')

    if not apply:
        return (len(corrupt_indices), 'would-repair')

    # Repair: substitute placeholder in each corrupt message
    for i in corrupt_indices:
        messages[i]['content'] = PLACEHOLDER
        messages[i].setdefault('tokens_used', 0)

    # Backup before writing
    backup_path = backup_dir / path.name
    if not backup_path.exists():
        shutil.copy2(path, backup_path)

    # Atomic write: write to temp file in same dir, then rename
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f'.{path.name}.repair.',
            suffix='.tmp',
        )
        try:
            with os.fdopen(fd, 'w') as f:
                if is_wrapped:
                    json.dump(data, f, indent=2, default=str)
                else:
                    json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return (0, f'error: write failed: {e}')

    return (len(corrupt_indices), 'repaired')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true',
                        help='Actually repair files (default is dry-run)')
    parser.add_argument('--conv-dir', type=Path, default=CONV_DIR,
                        help=f'Conversations directory (default: {CONV_DIR})')
    parser.add_argument('--backup-dir', type=Path, default=None,
                        help='Backup directory (default: <conv-dir>/.bulk-repair-2026-07-05/)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print every file processed, not just repaired ones')
    args = parser.parse_args()

    conv_dir: Path = args.conv_dir
    if not conv_dir.is_dir():
        print(f'ERROR: conversations dir not found: {conv_dir}', file=sys.stderr)
        sys.exit(1)

    if args.backup_dir is None:
        backup_dir = conv_dir / '.bulk-repair-2026-07-05'
    else:
        backup_dir = args.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Find all JSON files (skip .bak.* backups and the backup dir itself)
    candidates = []
    for entry in conv_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix != '.json':
            continue
        if entry.name.startswith('.'):
            continue  # skip hidden files (e.g. .bulk-repair-*)
        candidates.append(entry)
    candidates.sort()

    # Aggregate stats
    total_files = len(candidates)
    total_corrupt = 0
    total_repaired = 0
    files_repaired = 0
    files_skipped = 0
    files_errored = 0
    errors = []

    print(f'{"DRY RUN" if not args.apply else "APPLY MODE"} — scanning {total_files} files')
    print(f'Conversations dir: {conv_dir}')
    print(f'Backup dir:        {backup_dir}')
    print()

    for path in candidates:
        n, action = repair_file(path, backup_dir, apply=args.apply)
        if action == 'repaired':
            total_repaired += n
            files_repaired += 1
            total_corrupt += n
            print(f'  REPAIRED  {n:4d}  {path.name}')
        elif action == 'would-repair':
            total_repaired += n
            files_repaired += 1
            total_corrupt += n
            print(f'  WOULD      {n:4d}  {path.name}')
        elif action.startswith('error'):
            files_errored += 1
            errors.append((path, action))
            print(f'  ERROR     {path.name}: {action}')
        elif action == 'skipped':
            files_skipped += 1
            if args.verbose:
                print(f'  skip       ----  {path.name}')

    print()
    print('=' * 70)
    print(f'Files scanned:    {total_files}')
    print(f'Files repaired:   {files_repaired}')
    print(f'Files skipped:    {files_skipped}')
    print(f'Files errored:    {files_errored}')
    print(f'Corrupt messages: {total_corrupt} ({"would be repaired" if not args.apply else "repaired"})')
    print(f'Backups stored:   {backup_dir}')
    if errors:
        print()
        print('ERRORS:')
        for path, action in errors:
            print(f'  {path}: {action}')
        sys.exit(1)


if __name__ == '__main__':
    main()
