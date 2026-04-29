# tests/test_feed_card.py
# Unit tests for models/feed_card.py — FeedCardData dataclass.
#
# Principle: test the contract — dataclass fields, css_class_for_type,
# and any runtime field behavior.

import pytest
from datetime import datetime, timezone
from models.feed_card import FeedCardData, CardType, CardSource


# ═══════════════════════════════════════════════════════════════════
#  FeedCardData field initialization
# ═══════════════════════════════════════════════════════════════════

class TestFeedCardDataRequiredFields:
    """Required fields: all must be provided at construction."""

    def test_required_fields_set(self):
        ts = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
        card = FeedCardData(
            card_type="diff",
            source="agent",
            title="Fix auth bug",
            body="+from auth import middleware",
            author="Qat",
            timestamp=ts,
            project_name="manopea",
        )
        assert card.card_type == "diff"
        assert card.source == "agent"
        assert card.title == "Fix auth bug"
        assert card.body == "+from auth import middleware"
        assert card.author == "Qat"
        assert card.timestamp == ts
        assert card.project_name == "manopea"

    def test_required_fields_missing_raises(self):
        ts = datetime.now(timezone.utc)
        with pytest.raises(TypeError):
            FeedCardData(card_type="diff", source="agent", title="x",
                         body="y", author="z", timestamp=ts)
        # missing project_name


class TestFeedCardDataOptionalFields:
    """Optional context fields default to None."""

    def test_optional_context_fields_default_to_none(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
        )
        assert card.file_path is None
        assert card.commit_sha is None
        assert card.additions is None
        assert card.deletions is None
        assert card.task_id is None
        assert card.metadata == {}

    def test_optional_context_fields_can_be_set(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
            file_path="src/main.py",
            commit_sha="abc1234",
            additions=42,
            deletions=7,
            task_id="TASK-001",
            metadata={"key": "value"},
        )
        assert card.file_path == "src/main.py"
        assert card.commit_sha == "abc1234"
        assert card.additions == 42
        assert card.deletions == 7
        assert card.task_id == "TASK-001"
        assert card.metadata == {"key": "value"}


class TestFeedCardDataRuntimeFields:
    """Runtime fields (set by FeedHandler) default correctly."""

    def test_card_id_defaults_to_none(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="git_commit", source="agent", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
        )
        assert card.card_id is None

    def test_reviewed_defaults_to_false(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="git_commit", source="agent", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
        )
        assert card.reviewed is False

    def test_accepted_defaults_to_none(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="git_commit", source="agent", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
        )
        assert card.accepted is None  # pending

    def test_accepted_can_be_true(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="system", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
            accepted=True,
        )
        assert card.accepted is True

    def test_accepted_can_be_false(self):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="system", title="x",
            body="y", author="z", timestamp=ts, project_name="p",
            accepted=False,
        )
        assert card.accepted is False


# ═══════════════════════════════════════════════════════════════════
#  css_class_for_type()
# ═══════════════════════════════════════════════════════════════════

class TestCssClassForType:
    """Map card types to CSS class names."""

    @pytest.mark.parametrize("card_type,expected", [
        ("git_commit", "feed-card-git"),
        ("diff", "feed-card-diff"),
        ("file_created", "feed-card-file-new"),
        ("file_deleted", "feed-card-file-del"),
        ("dir_created", "feed-card-dir-new"),
        ("agent_action", "feed-card-agent"),
        ("task", "feed-card-task"),
        ("system", "feed-card-system"),
    ])
    def test_known_types_return_correct_class(self, card_type, expected):
        assert FeedCardData.css_class_for_type(card_type) == expected

    def test_unknown_type_returns_system_class(self):
        assert FeedCardData.css_class_for_type("unknown_type") == "feed-card-system"
        assert FeedCardData.css_class_for_type("") == "feed-card-system"
        assert FeedCardData.css_class_for_type("not_a_card") == "feed-card-system"


# ═══════════════════════════════════════════════════════════════════
#  All seven card types are constructable
# ═══════════════════════════════════════════════════════════════════

class TestAllCardTypes:
    """Every card_type value in CardType Literal is constructable."""

    @pytest.mark.parametrize("card_type", [
        "git_commit",
        "diff",
        "file_created",
        "file_deleted",
        "dir_created",
        "agent_action",
        "task",
        "system",
    ])
    def test_card_type_constructable(self, card_type):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type=card_type,
            source="agent",
            title=f"Test {card_type}",
            body="body",
            author="test",
            timestamp=ts,
            project_name="test-project",
        )
        assert card.card_type == card_type


# ═══════════════════════════════════════════════════════════════════
#  All four card sources are constructable
# ═══════════════════════════════════════════════════════════════════

class TestAllCardSources:
    """Every CardSource value is constructable."""

    @pytest.mark.parametrize("source", ["agent", "system", "git", "crabwatch"])
    def test_card_source_constructable(self, source):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff",
            source=source,
            title="Test",
            body="body",
            author="test",
            timestamp=ts,
            project_name="test-project",
        )
        assert card.source == source