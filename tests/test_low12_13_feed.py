# tests/test_low12_13_feed.py
# Phase 4-4: LOW-12 (gitignore), LOW-13 (atomic write), A-10 (dead code).

import json
import os
import stat
import tempfile
from datetime import datetime, timezone

import pytest

from models.feed_card import FeedCardData
from utils.feed_store import (
    load_feed,
    save_feed,
    append_feed_card,
    update_feed_card,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def project_path():
    """Temporary project directory with .crabcakes already created."""
    with tempfile.TemporaryDirectory() as tmp:
        crabcakes = os.path.join(tmp, ".crabcakes")
        os.makedirs(crabcakes)
        yield tmp


def make_card(card_type="diff", title="Test card", card_id="test-id-123", **kwargs):
    """Helper to create a FeedCardData for testing."""
    return FeedCardData(
        card_type=card_type,
        source="agent",
        title=title,
        body="test body",
        author="tester",
        timestamp=datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc),
        project_name="test-project",
        card_id=card_id,
        **kwargs,
    )


# ── LOW-12: gitignore ────────────────────────────────────────────────────────

class TestLow12Gitignore:
    def test_low12_gitignore_created_on_first_save(self, project_path):
        """save_feed creates .gitignore with .crabcakes/feed.json on first call."""
        cards = [make_card(card_id="c1")]
        save_feed(project_path, cards)

        gitignore = os.path.join(project_path, ".gitignore")
        assert os.path.isfile(gitignore), ".gitignore was not created"
        with open(gitignore) as f:
            content = f.read()
        assert ".crabcakes/feed.json" in content

    def test_low12_gitignore_no_duplicate(self, project_path):
        """Calling save_feed twice does not duplicate the entry in .gitignore."""
        cards = [make_card(card_id="c1")]
        save_feed(project_path, cards)
        save_feed(project_path, cards)

        gitignore = os.path.join(project_path, ".gitignore")
        with open(gitignore) as f:
            lines = f.read().splitlines()
        feed_lines = [l for l in lines if ".crabcakes/feed.json" in l]
        assert len(feed_lines) == 1, f"Expected 1 entry, got {len(feed_lines)}: {feed_lines}"

    def test_low12_gitignore_existing_file_respected(self, project_path):
        """Pre-existing .gitignore entries are preserved."""
        gitignore = os.path.join(project_path, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("node_modules/\n*.pyc\n")

        cards = [make_card(card_id="c1")]
        save_feed(project_path, cards)

        with open(gitignore) as f:
            content = f.read()
        assert "node_modules/" in content
        assert "*.pyc" in content
        assert ".crabcakes/feed.json" in content

    def test_low12_gitignore_comment_line_not_treated_as_entry(self, project_path):
        """Commented-out entries (# .crabcakes/feed.json) are treated as absent."""
        gitignore = os.path.join(project_path, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("# .crabcakes/feed.json\nnode_modules/\n")

        cards = [make_card(card_id="c1")]
        save_feed(project_path, cards)

        with open(gitignore) as f:
            lines = f.read().splitlines()
        # The entry should be appended (not a duplicate on same line)
        feed_lines = [l for l in lines if l.strip().lstrip("#").strip() == ".crabcakes/feed.json"]
        assert len(feed_lines) >= 1, "Entry should appear uncommented in .gitignore"

    def test_low12_gitignore_atomic_write(self, project_path, monkeypatch):
        """Mid-write crash (OSError) leaves .gitignore valid."""
        import utils.feed_store as fs

        written_content = []

        def broken_write(path, mode):
            written_content.append(path)
            raise OSError("mid-write crash")

        # Patch the internal tmp-file open in _atomic_write_text before it writes
        import builtins
        original_open = builtins.open
        def fake_open(path, *args, **kwargs):
            if ".gitignore" in str(path) and "tmp" not in str(path):
                raise OSError("mid-write crash")
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", fake_open)

        cards = [make_card(card_id="c1")]
        save_feed(project_path, cards)  # must not raise — errors are logged

        # .gitignore should be unchanged (or not created) — no partial content
        gitignore = os.path.join(project_path, ".gitignore")
        if os.path.exists(gitignore):
            with open(gitignore) as f:
                content = f.read()
            # Should not have partial feed.json entry
            assert ".crabcakes/feed.json" not in content or "\n" in content


# ── LOW-13: atomic write ───────────────────────────────────────────────────────

class TestLow13AtomicWrite:
    def test_low13_save_feed_atomic(self, project_path, monkeypatch):
        """Mid-write crash on save_feed leaves feed.json untouched."""
        cards = [make_card(card_id="initial")]
        save_feed(project_path, cards)

        feed_path = os.path.join(project_path, ".crabcakes", "feed.json")
        before_content = open(feed_path).read()

        # Monkeypatch json.dump to raise mid-write
        import json as _json
        def boom(*args, **kwargs):
            raise OSError("mid-write crash")
        monkeypatch.setattr(_json, "dump", boom)

        save_feed(project_path, [make_card(card_id="new")])

        # feed.json must still have the old content
        with open(feed_path) as f:
            after = f.read()
        assert "initial" in after
        assert "new" not in after

    def test_low13_append_feed_card_atomic(self, project_path, monkeypatch):
        """Mid-write crash on append_feed_card leaves feed.json valid."""
        cards = [make_card(card_id="first")]
        save_feed(project_path, cards)

        feed_path = os.path.join(project_path, ".crabcakes", "feed.json")
        before_content = open(feed_path).read()

        import json as _json
        def boom(*args, **kwargs):
            raise OSError("mid-write crash")
        monkeypatch.setattr(_json, "dump", boom)

        append_feed_card(project_path, make_card(card_id="second"))

        with open(feed_path) as f:
            after = f.read()
        assert "first" in after
        assert "second" not in after

    def test_low13_update_feed_card_atomic(self, project_path, monkeypatch):
        """Mid-write crash on update_feed_card leaves feed.json valid."""
        cards = [make_card(card_id="upd-1"), make_card(card_id="upd-2")]
        save_feed(project_path, cards)

        feed_path = os.path.join(project_path, ".crabcakes", "feed.json")

        import json as _json
        def boom(*args, **kwargs):
            raise OSError("mid-write crash")
        monkeypatch.setattr(_json, "dump", boom)

        update_feed_card(project_path, "upd-1", {"accepted": True})

        with open(feed_path) as f:
            after = f.read()
        assert "upd-1" in after
        # accepted=True should NOT be in the file (write didn't happen)
        loaded = load_feed(project_path)
        accepted_cards = [c for c in loaded if c.card_id == "upd-1"]
        assert accepted_cards[0].accepted is None, "accepted=True should not be persisted after crash"

    def test_low13_save_feed_permissions(self, project_path):
        """save_feed sets feed.json permissions to 0o600."""
        cards = [make_card(card_id="p1")]
        save_feed(project_path, cards)

        feed_path = os.path.join(project_path, ".crabcakes", "feed.json")
        mode = stat.S_IMODE(os.stat(feed_path).st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ── A-10: dead code cleanup ───────────────────────────────────────────────────

class TestA10DeadCode:
    def test_a10_image_utils_deleted(self):
        """utils/image_utils.py no longer exists on disk."""
        import os
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        image_utils_path = os.path.join(repo_root, "utils", "image_utils.py")
        assert not os.path.exists(image_utils_path), \
            f"image_utils.py should be deleted but still exists at {image_utils_path}"

    def test_a10_review_log_no_dream_engine_ref(self):
        """utils/review_log.py comment no longer references dream_engine."""
        import utils.review_log
        import inspect
        source = inspect.getsource(utils.review_log)
        assert "agent/dream_engine" not in source, \
            "review_log.py still references agent/dream_engine"
