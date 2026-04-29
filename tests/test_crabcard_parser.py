# tests/test_crabcard_parser.py
# Unit tests for utils/crabcard_parser.py — pure parser functions.

import pytest
from datetime import datetime, timezone

from models.feed_card import FeedCardData
from utils.crabcard_parser import (
    extract_crabcards,
    is_crabcards_placeholder,
    get_placeholder_index,
    _CRABCARD_PLACEHOLDER,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_card(**kwargs):
    """Helper — create FeedCardData with defaults."""
    defaults = dict(
        card_type="diff",
        source="agent",
        title="Test",
        body="Body",
        author="tester",
        timestamp=datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc),
        project_name="test-project",
    )
    defaults.update(kwargs)
    return FeedCardData(**defaults)


# ── extract_crabcards: basic parsing ─────────────────────────────────────────

class TestExtractBasic:
    def test_parses_single_crabcard(self):
        text = """Here's what I did:

```crabcard
type: diff
title: Added auth middleware
file: src/main.py
---
+from auth import middleware
+app.use(middleware())
```
"""
        cleaned, cards = extract_crabcards(text, "test-project", "Qaster")

        assert len(cards) == 1
        assert cards[0].card_type == "diff"
        assert cards[0].title == "Added auth middleware"
        assert cards[0].file_path == "src/main.py"
        assert cards[0].body == "+from auth import middleware\n+app.use(middleware())"
        assert cards[0].author == "Qaster"
        assert cards[0].source == "agent"
        assert cards[0].project_name == "test-project"
        # Cleaned text has placeholder marker
        assert _CRABCARD_PLACEHOLDER[:10] in cleaned

    def test_parses_multiple_crabcards(self):
        text = """```crabcard
type: diff
title: Card 1
---
body1
```
Some text between
```crabcard
type: file_created
title: Card 2
file: new.py
---
body2
```"""
        cleaned, cards = extract_crabcards(text, "proj", "agent")
        assert len(cards) == 2
        assert cards[0].title == "Card 1"
        assert cards[1].title == "Card 2"

    def test_empty_body(self):
        text = """```crabcard
type: git_commit
title: Init commit
---
```"""
        _, cards = extract_crabcards(text, "proj", "agent")
        assert len(cards) == 1
        assert cards[0].body == ""

    def test_no_crabcards_returns_original_text(self):
        text = "This is just plain text with no crabcard blocks."
        cleaned, cards = extract_crabcards(text, "proj", "agent")
        assert cleaned == text
        assert cards == []

    def test_malformed_crabcard_kept_in_cleaned_text(self):
        # Missing required "type" field
        text = """```crabcard
title: Missing type field
---
body
```"""
        cleaned, cards = extract_crabcards(text, "proj", "agent")
        # Malformed → returned as part of cleaned text (not dropped)
        assert _CRABCARD_PLACEHOLDER[:10] not in cleaned
        assert "```crabcard" in cleaned  # original block preserved


# ── extract_crabcards: field parsing ──────────────────────────────────────────

class TestFieldParsing:
    def test_all_optional_fields(self):
        text = """```crabcard
type: diff
title: Multi-field card
file: src/main.py
additions: 12
deletions: 3
commit_sha: abc1234
task_id: TASK-42
---
diff body
```"""
        _, cards = extract_crabcards(text, "proj", "author")
        c = cards[0]
        assert c.file_path == "src/main.py"
        assert c.additions == 12
        assert c.deletions == 3
        assert c.commit_sha == "abc1234"
        assert c.task_id == "TASK-42"

    def test_additions_deletions_non_numeric_ignored(self):
        text = """```crabcard
type: diff
title: X
additions: not-a-number
deletions: also-not
---
```"""
        _, cards = extract_crabcards(text, "proj", "agent")
        assert cards[0].additions is None
        assert cards[0].deletions is None

    def test_case_insensitive_field_keys(self):
        text = """```crabcard
TYPE: diff
TITLE: Case test
FILE: path.py
---
```"""
        _, cards = extract_crabcards(text, "proj", "agent")
        assert cards[0].card_type == "diff"
        assert cards[0].title == "Case test"
        assert cards[0].file_path == "path.py"


# ── extract_crabcards: cleaned text ───────────────────────────────────────────

class TestCleanedText:
    def test_placeholder_inserted_for_each_card(self):
        text = """```crabcard
type: diff
title: Card 1
---
```
```crabcard
type: diff
title: Card 2
---
```"""
        cleaned, cards = extract_crabcards(text, "proj", "agent")
        assert len(cards) == 2
        assert cleaned.count(_CRABCARD_PLACEHOLDER[:10]) == 2

    def test_text_around_crabcards_preserved(self):
        text = "Before\n```crabcard\ntype: diff\ntitle: X\n---\n```\nAfter"
        cleaned, cards = extract_crabcards(text, "proj", "agent")
        assert "Before" in cleaned
        assert "After" in cleaned


# ── Placeholder utilities ──────────────────────────────────────────────────────

class TestPlaceholderUtilities:
    def test_is_crabcards_placeholder_true(self):
        placeholder = _CRABCARD_PLACEHOLDER % 5
        assert is_crabcards_placeholder(placeholder) is True

    def test_is_crabcards_placeholder_false_regular_text(self):
        assert is_crabcards_placeholder("Hello world") is False

    def test_get_placeholder_index_valid(self):
        placeholder = _CRABCARD_PLACEHOLDER % 42
        assert get_placeholder_index(placeholder) == 42

    def test_get_placeholder_index_invalid(self):
        assert get_placeholder_index("not a placeholder") is None
        assert get_placeholder_index("CRABCARD_REF:abc\x00") is None


# ── FeedCardData construction ─────────────────────────────────────────────────

class TestFeedCardDataFields:
    def test_source_is_agent(self):
        text = """```crabcard
type: diff
title: X
---
```"""
        _, cards = extract_crabcards(text, "proj", "MyAgent")
        assert cards[0].source == "agent"
        assert cards[0].author == "MyAgent"

    def test_timestamp_is_set(self):
        text = """```crabcard
type: diff
title: X
---
```"""
        _, cards = extract_crabcards(text, "proj", "agent")
        assert isinstance(cards[0].timestamp, datetime)

    def test_project_name_set(self):
        text = """```crabcard
type: diff
title: X
---
```"""
        _, cards = extract_crabcards(text, "my-special-project", "agent")
        assert cards[0].project_name == "my-special-project"