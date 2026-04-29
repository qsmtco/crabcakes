# tests/test_feed_store.py
# Unit tests for utils/feed_store.py — pure persistence functions.

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

from models.feed_card import FeedCardData
from utils.feed_store import (
    FEED_FILENAME,
    load_feed,
    save_feed,
    append_feed_card,
    update_feed_card,
)


@pytest.fixture
def project_path():
    """Temporary project directory with .crabcakes."""
    with tempfile.TemporaryDirectory() as tmp:
        crabcakes = os.path.join(tmp, ".crabcakes")
        os.makedirs(crabcakes)
        yield tmp


def make_card(
    card_type="diff",
    title="Test card",
    project_name="test-project",
    card_id="test-id-123",
    accepted=None,
    **kwargs,
):
    """Helper to create a FeedCardData for testing."""
    return FeedCardData(
        card_type=card_type,
        source="agent",
        title=title,
        body="test body",
        author="tester",
        timestamp=datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc),
        project_name=project_name,
        card_id=card_id,
        accepted=accepted,
        **kwargs,
    )


class TestSaveAndLoad:
    def test_save_then_load_round_trip(self, project_path):
        cards = [
            make_card("diff", "Card 1", card_id="c1"),
            make_card("git_commit", "Card 2", card_id="c2"),
        ]
        save_feed(project_path, cards)
        loaded = load_feed(project_path)
        assert len(loaded) == 2
        assert loaded[0].card_id == "c1"
        assert loaded[1].card_id == "c2"
        assert loaded[0].card_type == "diff"
        assert loaded[1].card_type == "git_commit"

    def test_load_nonexistent_returns_empty_list(self, project_path):
        result = load_feed(project_path)
        assert result == []

    def test_save_creates_crabcakes_dir(self, project_path):
        # Remove .crabcakes to test creation
        os.rmdir(os.path.join(project_path, ".crabcakes"))
        cards = [make_card()]
        save_feed(project_path, cards)
        assert os.path.isdir(os.path.join(project_path, ".crabcakes"))
        assert os.path.isfile(os.path.join(project_path, ".crabcakes", FEED_FILENAME))


class TestAppendFeedCard:
    def test_append_adds_to_empty_file(self, project_path):
        card = make_card("diff", card_id="ap-1")
        append_feed_card(project_path, card)
        loaded = load_feed(project_path)
        assert len(loaded) == 1
        assert loaded[0].card_id == "ap-1"

    def test_append_adds_to_existing(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="ex-1")])
        append_feed_card(project_path, make_card("git_commit", card_id="ex-2"))
        loaded = load_feed(project_path)
        assert len(loaded) == 2
        assert loaded[0].card_id == "ex-1"
        assert loaded[1].card_id == "ex-2"

    def test_append_persists_all_fields(self, project_path):
        card = make_card(
            "diff",
            card_id="fields-1",
            file_path="src/main.py",
            additions=10,
            deletions=3,
            accepted=True,
        )
        append_feed_card(project_path, card)
        loaded = load_feed(project_path)
        assert len(loaded) == 1
        assert loaded[0].file_path == "src/main.py"
        assert loaded[0].additions == 10
        assert loaded[0].deletions == 3
        assert loaded[0].accepted is True


class TestUpdateFeedCard:
    def test_update_existing_card_accepted(self, project_path):
        cards = [make_card("diff", card_id="upd-1"), make_card("diff", card_id="upd-2")]
        save_feed(project_path, cards)

        result = update_feed_card(project_path, "upd-1", {"accepted": True})
        assert result is True

        loaded = load_feed(project_path)
        assert loaded[0].accepted is True
        assert loaded[1].accepted is None  # unchanged

    def test_update_nonexistent_returns_false(self, project_path):
        result = update_feed_card(project_path, "nonexistent", {"accepted": True})
        assert result is False

    def test_update_reviewed_flag(self, project_path):
        card = make_card("task", card_id="rev-1", reviewed=False)
        save_feed(project_path, [card])
        update_feed_card(project_path, "rev-1", {"reviewed": True})
        loaded = load_feed(project_path)
        assert loaded[0].reviewed is True


class TestFileFormat:
    def test_feed_json_is_valid_json(self, project_path):
        cards = [make_card("diff", card_id="fmt-1")]
        save_feed(project_path, cards)
        path = os.path.join(project_path, ".crabcakes", FEED_FILENAME)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_timestamp_round_trips(self, project_path):
        card = make_card(card_id="ts-1")
        save_feed(project_path, [card])
        loaded = load_feed(project_path)
        assert loaded[0].timestamp.isoformat() == "2026-04-28T12:00:00+00:00"

    def test_malformed_json_returns_empty_list(self, project_path):
        path = os.path.join(project_path, ".crabcakes", FEED_FILENAME)
        with open(path, "w") as f:
            f.write("{ invalid json }")
        result = load_feed(project_path)
        assert result == []

    def test_malformed_card_item_skipped(self, project_path):
        path = os.path.join(project_path, ".crabcakes", FEED_FILENAME)
        with open(path, "w") as f:
            json.dump([{"card_type": "diff", "source": "agent", "title": "X",
                        "author": "y", "timestamp": "2026-04-28T12:00:00+00:00",
                        "project_name": "p"}, {"invalid": "card"}], f)
        result = load_feed(project_path)
        assert len(result) == 1  # skips the malformed second card