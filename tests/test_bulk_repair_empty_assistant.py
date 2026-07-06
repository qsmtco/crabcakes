"""
Tests for scripts/bulk_repair_empty_assistant.py.

The bulk repair tool walks a conversations directory and substitutes a
placeholder for empty-content + no-tool-calls assistant messages. These
tests verify the corruption detection and repair logic against a synthetic
in-memory fixture set (no real conversation files are touched).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'scripts' / 'bulk_repair_empty_assistant.py'
PLACEHOLDER = '[assistant returned no content — placeholder]'

# ─── Pure-logic tests (no subprocess) ────────────────────────────────────────


def _make_conv(messages):
    return {'agent_name': 'test-agent', 'messages': messages}


def _write_conv(path: Path, data):
    path.write_text(json.dumps(data, indent=2))


class TestIsCorrupt:
    """Test the corruption predicate by importing the script as a module."""

    @pytest.fixture(autouse=True)
    def load_script(self):
        # Add scripts/ to path and import the module dynamically
        sys.path.insert(0, str(SCRIPT.parent))
        from bulk_repair_empty_assistant import is_corrupt
        self.is_corrupt = is_corrupt

    def test_empty_content_no_tool_calls_is_corrupt(self):
        msg = {'role': 'assistant', 'content': '', 'tool_calls': []}
        assert self.is_corrupt(msg) is True

    def test_empty_content_missing_tool_calls_is_corrupt(self):
        """tool_calls key absent → defaults to [] → corrupt."""
        msg = {'role': 'assistant', 'content': ''}
        assert self.is_corrupt(msg) is True

    def test_with_tool_calls_not_corrupt(self):
        msg = {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'x'}]}
        assert self.is_corrupt(msg) is False

    def test_with_content_not_corrupt(self):
        msg = {'role': 'assistant', 'content': 'hello', 'tool_calls': []}
        assert self.is_corrupt(msg) is False

    def test_user_role_not_corrupt(self):
        """Only assistant messages are checked."""
        msg = {'role': 'user', 'content': '', 'tool_calls': []}
        assert self.is_corrupt(msg) is False

    def test_tool_role_not_corrupt(self):
        msg = {'role': 'tool', 'content': '', 'tool_calls': []}
        assert self.is_corrupt(msg) is False


class TestFindCorruptIndices:
    @pytest.fixture(autouse=True)
    def load_script(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from bulk_repair_empty_assistant import find_corrupt_indices
        self.find = find_corrupt_indices

    def test_empty_list(self):
        assert self.find([]) == []

    def test_clean_messages(self):
        msgs = [
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'hello'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'x'}]},
        ]
        assert self.find(msgs) == []

    def test_mixed(self):
        msgs = [
            {'role': 'user', 'content': 'q1'},
            {'role': 'assistant', 'content': '', 'tool_calls': []},  # corrupt
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'q2'},
            {'role': 'assistant', 'content': '', 'tool_calls': []},  # corrupt
        ]
        assert self.find(msgs) == [1, 4]

    def test_preserves_order(self):
        msgs = [{'role': 'assistant', 'content': '', 'tool_calls': []} for _ in range(5)]
        assert self.find(msgs) == [0, 1, 2, 3, 4]


class TestRepairFile:
    """End-to-end tests using a temp directory of fake conversation files."""

    @pytest.fixture(autouse=True)
    def load_script(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from bulk_repair_empty_assistant import repair_file
        self.repair = repair_file

    @pytest.fixture
    def tmp_conv_dir(self, tmp_path):
        conv_dir = tmp_path / 'conversations'
        conv_dir.mkdir()
        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        return conv_dir, backup_dir

    def test_repair_substitutes_placeholder(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'a.json'
        _write_conv(p, _make_conv([
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ]))

        n, action = self.repair(p, backup_dir, apply=True)
        assert n == 1
        assert action == 'repaired'

        data = json.loads(p.read_text())
        assert data['messages'][1]['content'] == PLACEHOLDER

    def test_repair_preserves_other_keys(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'b.json'
        _write_conv(p, _make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': [],
             'timestamp': '2026-01-01T00:00:00', 'tokens_used': 0, 'tool_call_id': None}
        ]))

        self.repair(p, backup_dir, apply=True)
        m = json.loads(p.read_text())['messages'][0]
        assert m['content'] == PLACEHOLDER
        assert m['timestamp'] == '2026-01-01T00:00:00'
        assert m['tokens_used'] == 0
        assert m['tool_call_id'] is None

    def test_dry_run_does_not_modify(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'c.json'
        original = _make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ])
        _write_conv(p, original)

        n, action = self.repair(p, backup_dir, apply=False)
        assert n == 1
        assert action == 'would-repair'

        # File must be unchanged
        assert json.loads(p.read_text()) == original
        # No backup created in dry-run
        assert list(backup_dir.iterdir()) == []

    def test_skips_clean_file(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'd.json'
        _write_conv(p, _make_conv([
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'hello'},
        ]))

        n, action = self.repair(p, backup_dir, apply=True)
        assert n == 0
        assert action == 'skipped'

    def test_handles_malformed_json(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'broken.json'
        p.write_text('{not valid json')

        n, action = self.repair(p, backup_dir, apply=True)
        assert n == 0
        assert action.startswith('error')

    def test_handles_root_list_format(self, tmp_conv_dir):
        """Some files may be a bare list of messages, not a wrapped dict."""
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'list-format.json'
        _write_conv(p, [
            {'role': 'assistant', 'content': '', 'tool_calls': []},
            {'role': 'user', 'content': 'q'},
        ])

        n, action = self.repair(p, backup_dir, apply=True)
        assert n == 1
        assert action == 'repaired'

        # File should still be a list (not wrapped)
        data = json.loads(p.read_text())
        assert isinstance(data, list)
        assert data[0]['content'] == PLACEHOLDER

    def test_backup_created_on_apply(self, tmp_conv_dir):
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'with-backup.json'
        _write_conv(p, _make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ]))

        self.repair(p, backup_dir, apply=True)
        backup = backup_dir / 'with-backup.json'
        assert backup.exists()

        # Backup contains the pre-repair state
        backup_data = json.loads(backup.read_text())
        assert backup_data['messages'][0]['content'] == ''

    def test_idempotent(self, tmp_conv_dir):
        """Running repair twice is a no-op the second time."""
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'idem.json'
        _write_conv(p, _make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ]))

        n1, a1 = self.repair(p, backup_dir, apply=True)
        n2, a2 = self.repair(p, backup_dir, apply=True)
        assert n1 == 1 and a1 == 'repaired'
        assert n2 == 0 and a2 == 'skipped'

    def test_repair_does_not_create_duplicate_backup(self, tmp_conv_dir):
        """Backup is created only on first repair, not re-created."""
        conv_dir, backup_dir = tmp_conv_dir
        p = conv_dir / 'no-dup.json'
        _write_conv(p, _make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ]))

        self.repair(p, backup_dir, apply=True)
        first_backup_mtime = (backup_dir / 'no-dup.json').stat().st_mtime

        # Repair again with re-corrupted file
        data = json.loads(p.read_text())
        data['messages'][0]['content'] = ''  # re-corrupt
        p.write_text(json.dumps(data))

        self.repair(p, backup_dir, apply=True)
        # Backup mtime should be unchanged (not overwritten)
        assert (backup_dir / 'no-dup.json').stat().st_mtime == first_backup_mtime


# ─── Subprocess integration test ─────────────────────────────────────────────


class TestSubprocessDryRun:
    """Run the script as a subprocess against a temp directory."""

    def test_dry_run_summary(self, tmp_path):
        # Set up 3 files: 2 corrupt, 1 clean
        conv_dir = tmp_path / 'conversations'
        conv_dir.mkdir()

        (conv_dir / 'clean.json').write_text(json.dumps(_make_conv([
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'hello'},
        ])))
        (conv_dir / 'corrupt1.json').write_text(json.dumps(_make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ])))
        (conv_dir / 'corrupt2.json').write_text(json.dumps(_make_conv([
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': '', 'tool_calls': []},
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ])))

        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--conv-dir', str(conv_dir),
             '--backup-dir', str(tmp_path / 'backups')],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f'stderr: {result.stderr}'

        # Dry run should not modify any file
        for fname in ['clean.json', 'corrupt1.json', 'corrupt2.json']:
            content = (conv_dir / fname).read_text()
            assert 'placeholder' not in content, f'{fname} should not have been modified'

        # Stats should match
        assert 'Files scanned:    3' in result.stdout
        assert 'Files repaired:   2' in result.stdout
        assert 'Corrupt messages: 3' in result.stdout

    def test_apply_modifies_files(self, tmp_path):
        conv_dir = tmp_path / 'conversations'
        conv_dir.mkdir()

        (conv_dir / 'c.json').write_text(json.dumps(_make_conv([
            {'role': 'assistant', 'content': '', 'tool_calls': []},
        ])))

        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--apply',
             '--conv-dir', str(conv_dir),
             '--backup-dir', str(tmp_path / 'backups')],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f'stderr: {result.stderr}'

        # File should now have placeholder
        data = json.loads((conv_dir / 'c.json').read_text())
        assert data['messages'][0]['content'] == PLACEHOLDER

        # Backup should exist with original content
        backup = tmp_path / 'backups' / 'c.json'
        assert backup.exists()
        backup_data = json.loads(backup.read_text())
        assert backup_data['messages'][0]['content'] == ''
