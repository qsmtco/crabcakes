# tests/test_feed_store.py
# Unit tests for utils/feed_store.py — pure persistence functions.

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

import pytest

import utils.feed_store as fs
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


def make_feed(n, project_name="test-project"):
    """Synthetic feed fixture: n cards with stable ids.

    Shared by the Phase-2 perf tests and reused by Phase 3 (spec §9).
    """
    return [
        make_card("diff", title=f"card {i}", project_name=project_name, card_id=f"perf-{i}")
        for i in range(n)
    ]


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

    def test_update_nonexistent_tri_state(self, project_path, monkeypatch):
        """D4 (SPEC-UI-RESPONSIVENESS-2 Phase 2): the tri-state return.

        Journal path: True = "safely recorded" — existence is NOT checked
        O(1) (and cannot be). Legacy fallback: None = card not found
        (pruned between enqueue and drain) — the writer logs INFO and drops
        rather than retrying a gone card. False is reserved for a genuine
        write failure (lock timeout / OSError) on both paths.

        Rewritten from `test_update_nonexistent_returns_false`, whose
        `is False` assertion encoded the pre-journal semantics.
        """
        # ── Journal path: nonexistent card is still recorded ────────────
        assert update_feed_card(project_path, "nonexistent", {"accepted": True}) is True
        # No phantom card was created, and load_feed stays clean.
        assert load_feed(project_path) == []

        # ── Legacy path: force the journal append to fail ──────────────
        save_feed(project_path, [make_card("diff", card_id="real-1")])
        monkeypatch.setattr(fs, "append_card_update", lambda *a, **k: False)

        result = update_feed_card(project_path, "nonexistent", {"accepted": True})
        assert result is None, "legacy path + card not found must return None"
        # The existing card is untouched — no phantom, no collateral write.
        assert load_feed(project_path)[0].accepted is None

        # ── Legacy path + card PRESENT → True ──────────────────────────
        assert update_feed_card(project_path, "real-1", {"accepted": True}) is True
        assert load_feed(project_path)[0].accepted is True

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


# ═══════════════════════════════════════════════════════════════════
#  SPEC-UI-RESPONSIVENESS-2 Phase 2 — O(1) update journal + compaction
#  + bounded lock (§2.2). Red-first: every test below failed against the
#  pre-Phase-2 store (no journal exists at all).
# ═══════════════════════════════════════════════════════════════════

def _journal_lines(project_path) -> list[str]:
    """Raw non-empty lines of the journal file ([] when absent)."""
    jp = fs._journal_path(project_path)
    if not os.path.isfile(jp):
        return []
    with open(jp, "r", encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


class TestPhase2Constants:
    """E1 — the constants Phase 3 also depends on."""

    def test_journal_constants(self):
        assert fs.JOURNAL_FILENAME == "feed-updates.jsonl"
        assert fs.JOURNAL_COMPACT_THRESHOLD == 500
        assert fs._LOCK_TIMEOUT_SEC == 2.0
        assert fs._COMPACT_MIN_INTERVAL == 60.0

    def test_feed_window_default_defined_early(self):
        """Phase-3 constant, defined in Phase 2 to avoid signature churn."""
        assert fs.FEED_WINDOW_DEFAULT == 2000

    def test_updatable_fields_includes_body(self):
        """D3 — `body` was silently dropped by the old allowed set."""
        assert fs._UPDATABLE_FIELDS == frozenset(
            {"accepted", "reviewed", "metadata", "body"}
        )


class TestPhase1RaceClosure:
    """The Phase-1 interim race is closed by the journal path (D4).

    Phase 1 enqueued updates on the writer thread; if that write beat
    `add_card`'s own `append_feed_card` thread, the pre-Phase-2 store
    returned False for a card it could not find yet, so the writer retried
    3× and then ERROR-dropped the update — the on-disk card kept a stale
    body. The journal records the update without needing the card to exist.
    """

    def test_update_before_append_survives_to_load(self, project_path):
        # 1) feed.json does not exist yet — the append thread hasn't run.
        assert not os.path.isfile(fs._feed_path(project_path))

        # 2) The writer's update lands first. Pre-Phase-2 this returned False
        #    (no feed.json → "not found") and the update was dropped.
        assert update_feed_card(project_path, "race-1", {"accepted": True}) is True
        assert fs._journal_line_count(project_path) == 1

        # 3) The append finally lands.
        append_feed_card(project_path, make_card("diff", card_id="race-1"))

        # 4) Replay merges snapshot + journal: the update survived.
        loaded = load_feed(project_path)
        assert [c.card_id for c in loaded] == ["race-1"]
        assert loaded[0].accepted is True

    def test_update_before_append_survives_compaction(self, project_path):
        """The same race, but a compaction folds the journal afterwards."""
        update_feed_card(project_path, "race-2", {"body": "fresh body"})
        append_feed_card(project_path, make_card("diff", card_id="race-2"))
        fs.compact_feed(project_path)

        loaded = load_feed(project_path)
        assert loaded[0].card_id == "race-2"
        assert loaded[0].body == "fresh body", "D3: body now persists"


class TestJournalO1:
    """Invariant 1 — the hot path is O(1) and never reads feed.json."""

    def test_hot_path_does_not_json_load_feed_json(self, project_path, monkeypatch):
        save_feed(project_path, make_feed(500, project_name="test-project"))

        def _boom(*args, **kwargs):
            raise AssertionError("journal hot path must not json.load feed.json")

        # Structural assertion: the timing claim cannot mask a full-file read.
        monkeypatch.setattr(json, "load", _boom)
        assert update_feed_card(project_path, "perf-1", {"accepted": True}) is True

    def test_journal_append_time_is_feed_size_independent(self, project_path):
        """9,500-card feed within 3× of an empty feed (spec §6)."""
        import time

        big = os.path.join(project_path, "big")
        empty = os.path.join(project_path, "empty")
        os.makedirs(big)
        os.makedirs(empty)
        save_feed(big, make_feed(9500, project_name="test-project"))

        # Warm both paths (first call creates .crabcakes/journal/gitignore).
        update_feed_card(big, "perf-1", {"accepted": True})
        update_feed_card(empty, "perf-1", {"accepted": True})

        def _best_of(n, path):
            best = float("inf")
            for i in range(n):
                t0 = time.perf_counter()
                update_feed_card(path, "perf-1", {"accepted": i % 2 == 0})
                best = min(best, time.perf_counter() - t0)
            return best

        t_big = _best_of(5, big)
        t_empty = _best_of(5, empty)

        # Structural companion: the big feed's JSON was never rewritten.
        assert len(_journal_lines(big)) == 6
        assert t_big < max(t_empty * 3, 0.05), (
            f"journal append scaled with feed size: big={t_big:.5f}s "
            f"empty={t_empty:.5f}s"
        )


class TestJournalRoundTrip:
    """Invariants 2/3 + the D3 body regression test."""

    def test_journal_round_trip_all_updatable_fields(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="rt-1")])

        assert update_feed_card(project_path, "rt-1", {"accepted": True}) is True
        assert update_feed_card(project_path, "rt-1", {"reviewed": True}) is True
        assert update_feed_card(project_path, "rt-1", {"body": "new body"}) is True
        assert update_feed_card(project_path, "rt-1", {"metadata": {"k": "v"}}) is True

        loaded = load_feed(project_path)
        assert len(loaded) == 1
        assert loaded[0].accepted is True
        assert loaded[0].reviewed is True
        assert loaded[0].body == "new body"
        assert loaded[0].metadata.get("k") == "v"

        # The snapshot itself is untouched until compaction (D2) — the
        # journal is the source of the overlay.
        with open(fs._feed_path(project_path), encoding="utf-8") as f:
            raw = json.load(f)
        assert raw[0]["body"] == "test body"

    def test_body_update_persists_through_compaction(self, project_path):
        """D3 regression: body used to be silently dropped by the allowed set."""
        save_feed(project_path, [make_card("diff", card_id="body-1")])
        update_feed_card(project_path, "body-1", {"body": "fresh tool result"})
        fs.compact_feed(project_path)

        with open(fs._feed_path(project_path), encoding="utf-8") as f:
            raw = json.load(f)
        assert raw[0]["body"] == "fresh tool result"
        assert load_feed(project_path)[0].body == "fresh tool result"

    def test_journal_metadata_merges_per_key(self, project_path):
        save_feed(project_path, [
            make_card("diff", card_id="m1", metadata={"a": 1, "b": 2}),
        ])
        update_feed_card(project_path, "m1", {"metadata": {"b": 3, "c": 4}})
        loaded = load_feed(project_path)
        assert loaded[0].metadata == {"a": 1, "b": 3, "c": 4}

    def test_replay_is_idempotent(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="idem-1")])
        update_feed_card(project_path, "idem-1", {"accepted": True})
        before = _journal_lines(project_path)

        def _snapshot():
            return [(c.card_id, c.accepted, c.body) for c in load_feed(project_path)]

        first = _snapshot()
        second = _snapshot()
        assert first == second
        assert len(before) == 1
        assert _journal_lines(project_path) == before, "load_feed must never write"

    def test_stale_record_for_absent_card_is_dropped(self, project_path):
        """A journal record for a card the snapshot does not have is inert."""
        save_feed(project_path, [make_card("diff", card_id="present")])
        update_feed_card(project_path, "absent", {"accepted": True})

        loaded = load_feed(project_path)
        assert [c.card_id for c in loaded] == ["present"]
        assert loaded[0].accepted is None

    def test_empty_updates_dict_is_a_noop_record(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="e1")])
        assert update_feed_card(project_path, "e1", {}) is True
        assert load_feed(project_path)[0].accepted is None


class TestTornTail:
    """Invariant 3 + edge case: a torn final line must not destroy records."""

    def test_torn_tail_preserves_prior_records_with_one_warning(
        self, project_path, caplog
    ):
        save_feed(project_path, [
            make_card("diff", card_id="t1"),
            make_card("diff", card_id="t2"),
        ])
        update_feed_card(project_path, "t1", {"accepted": True})
        update_feed_card(project_path, "t2", {"reviewed": True})

        # Simulate a crash mid-append: an unparseable, newline-less tail.
        with open(fs._journal_path(project_path), "a", encoding="utf-8") as f:
            f.write('{"card_id": "t2", "updat')

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            loaded = load_feed(project_path)

        assert loaded[0].accepted is True, "prior records must survive"
        assert loaded[1].reviewed is True
        torn = [r for r in caplog.records if "torn" in r.getMessage().lower()]
        assert len(torn) == 1, f"expected exactly one torn-tail warning: {torn}"

    def test_append_repairs_garbage_tail_so_later_records_replay(self, project_path, caplog):
        """A torn tail must not shadow records appended after it.

        Design note (BUG found in-build): the spec's literal "prepend `\\n`"
        rule leaves the damaged bytes in the file, and `_replay_journal` stops
        at the first unparseable line — so every later record stays invisible
        AND is then silently discarded by the next compaction (which folds
        with the same stop-at-first-bad rule). The writer repairs the tail
        instead: garbage is truncated, a complete-newline-less record is kept.
        """
        save_feed(project_path, [make_card("diff", card_id="tt-1")])
        update_feed_card(project_path, "tt-1", {"accepted": True})
        with open(fs._journal_path(project_path), "a", encoding="utf-8") as f:
            f.write("{torn")  # crash mid-append: incomplete JSON, no newline

        assert update_feed_card(project_path, "tt-1", {"reviewed": True}) is True

        lines = _journal_lines(project_path)
        for line in lines:
            json.loads(line)  # every remaining line must be parseable

        loaded = load_feed(project_path)
        assert loaded[0].accepted is True, "the pre-tear record survives"
        assert loaded[0].reviewed is True, (
            "the post-tear record must be replayable, not shadowed by the tear"
        )

    def test_append_preserves_complete_record_missing_only_its_newline(
        self, project_path
    ):
        """The crash-after-bytes case: the final record is recovered, not lost."""
        jp = fs._journal_path(project_path)
        save_feed(project_path, [make_card("diff", card_id="tn-1")])
        record = json.dumps({"card_id": "tn-1", "updates": {"accepted": True}})
        with open(jp, "w", encoding="utf-8") as f:
            f.write(record)  # complete JSON, no trailing newline

        assert update_feed_card(project_path, "tn-1", {"reviewed": True}) is True

        loaded = load_feed(project_path)
        assert loaded[0].accepted is True, "a complete newline-less record is kept"
        assert loaded[0].reviewed is True

    def test_torn_tail_in_middle_of_journal_is_reported_once(self, project_path, caplog):
        """Read-side contract unchanged: replay stops at the first bad line."""
        save_feed(project_path, [
            make_card("diff", card_id="mid-1"),
            make_card("diff", card_id="mid-2"),
        ])
        jp = fs._journal_path(project_path)
        with open(jp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"card_id": "mid-1", "updates": {"accepted": True}}) + "\n")
            f.write("{broken\n")
            f.write(json.dumps({"card_id": "mid-2", "updates": {"reviewed": True}}) + "\n")

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            loaded = load_feed(project_path)

        assert loaded[0].accepted is True
        assert loaded[1].reviewed is False, "replay stops at the first bad line"
        torn = [r for r in caplog.records if "torn tail" in r.getMessage()]
        assert len(torn) == 1


class TestCompaction:
    """E8 — fold + truncate under one lock hold, no lock re-entry."""

    def test_compact_folds_journal_and_truncates(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="c1")])
        update_feed_card(project_path, "c1", {"accepted": True})
        assert fs._journal_line_count(project_path) == 1

        pruned = fs.compact_feed(project_path)  # window=None in Phase 2

        assert pruned == 0, "Phase 2 has no window pruning"
        assert fs._journal_line_count(project_path) == 0, "journal must be truncated"

        with open(fs._feed_path(project_path), encoding="utf-8") as f:
            raw = json.load(f)
        assert raw[0]["accepted"] is True, "folded into the snapshot"
        assert load_feed(project_path)[0].accepted is True

    def test_compact_uses_shared_helpers_not_load_feed(self, project_path, monkeypatch):
        """No lock re-entry: compact parses inline via _parse_cards."""
        save_feed(project_path, [make_card("diff", card_id="c2")])
        update_feed_card(project_path, "c2", {"accepted": True})

        def _boom(*args, **kwargs):
            raise AssertionError("compact_feed must not call load_feed")

        monkeypatch.setattr(fs, "load_feed", _boom)
        assert fs.compact_feed(project_path) == 0

    def test_compact_writes_compact_json(self, project_path):
        """E10 — feed snapshots lose `indent=2`; prefs keep it."""
        save_feed(project_path, [make_card("diff", card_id="cj")])
        with open(fs._feed_path(project_path), encoding="utf-8") as f:
            content = f.read()
        assert "\n" not in content.strip(), f"expected compact JSON, got: {content[:80]!r}"

    def test_compact_records_rate_limit_timestamp(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="rl")])
        fs._compact_last.pop(project_path, None)
        fs.compact_feed(project_path)
        assert project_path in fs._compact_last

    def test_compact_is_idempotent(self, project_path):
        save_feed(project_path, [make_card("diff", card_id="i1")])
        update_feed_card(project_path, "i1", {"accepted": True})
        fs.compact_feed(project_path)
        first = load_feed(project_path)[0].accepted
        fs.compact_feed(project_path)
        assert load_feed(project_path)[0].accepted is first is True


class TestBoundedLock:
    """Invariant 5 + E2 — never unbounded, on any path."""

    def test_acquire_lock_returns_none_within_bound(self, project_path):
        import fcntl
        import time

        path = fs._feed_path(project_path)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[]")

        held_fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            t0 = time.monotonic()
            got = fs._acquire_lock(path, timeout=0.2)
            elapsed = time.monotonic() - t0
            assert got is None, "must time out, never block unbounded"
            assert elapsed < 1.0, f"took {elapsed:.2f}s (bound 1.0s)"
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            os.close(held_fd)

    def test_write_paths_skip_and_warn_when_lock_unavailable(
        self, project_path, caplog, monkeypatch
    ):
        save_feed(project_path, [make_card("diff", card_id="w1")])
        monkeypatch.setattr(fs, "_acquire_lock", lambda *a, **k: None)

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            assert fs.append_card_update(project_path, "w1", {"accepted": True}) is False
            result = update_feed_card(project_path, "w1", {"accepted": True})

        # append failed AND legacy failed → False (defer-retry signal).
        assert result is False
        assert any("busy" in r.getMessage() for r in caplog.records), (
            [r.getMessage() for r in caplog.records]
        )

    def test_every_entry_point_tolerates_a_none_lock(self, project_path, monkeypatch):
        """A timed-out acquire must be handled, never unpacked.

        Regression guard for the `fd, lock_path = _acquire_lock(...)` pattern,
        which raises `TypeError: cannot unpack non-iterable NoneType` on the
        exact path the bounded lock was introduced for.
        """
        save_feed(project_path, [
            make_card("diff", card_id="nl-1"),
            make_card("diff", card_id="nl-2"),
        ])
        map_card = make_card("diff", card_id="nl-3")
        monkeypatch.setattr(fs, "_acquire_lock", lambda *a, **k: None)

        # None of these may raise; each returns its "skipped" shape.
        assert save_feed(project_path, [map_card]) is None
        assert append_feed_card(project_path, map_card) is None
        assert fs.append_card_update(project_path, "nl-1", {"accepted": True}) is False
        assert fs.compact_feed(project_path) == 0
        assert update_feed_card(project_path, "nl-1", {"accepted": True}) is False
        # load_feed degrades to a lock-free read rather than raising.
        assert [c.card_id for c in load_feed(project_path)] == ["nl-1", "nl-2"]
        # Nothing was written while the lock was unavailable.
        assert len(_journal_lines(project_path)) == 0

    def test_load_falls_back_lock_free_with_size_scaled_timeout(
        self, project_path, monkeypatch
    ):
        save_feed(project_path, [make_card("diff", card_id="lf-1")])
        captured = {}

        def _fake_acquire(path, timeout=fs._LOCK_TIMEOUT_SEC):
            captured["timeout"] = timeout
            return None

        monkeypatch.setattr(fs, "_acquire_lock", _fake_acquire)
        loaded = load_feed(project_path)

        assert [c.card_id for c in loaded] == ["lf-1"], "lock-free read must still work"
        size = os.path.getsize(fs._feed_path(project_path))
        assert captured["timeout"] == min(60.0, 10.0 + size / 1_000_000)

    def test_save_feed_acquires_the_lock(self, project_path, monkeypatch):
        calls = []
        real = fs._acquire_lock

        def _spy(path, timeout=fs._LOCK_TIMEOUT_SEC):
            calls.append(path)
            return real(path, timeout)

        monkeypatch.setattr(fs, "_acquire_lock", _spy)
        save_feed(project_path, [make_card("diff", card_id="sf-1")])
        assert len(calls) == 1, "save_feed must take the feed lock"
        assert load_feed(project_path)[0].card_id == "sf-1"

    def test_no_nested_flock_acquire_anywhere(self, project_path, monkeypatch):
        """Invariant 8 — no flock re-entrancy on any public path."""
        import threading

        depth = threading.local()
        observed = []
        real_acquire = fs._acquire_lock
        real_release = fs._release_lock

        def _acquire(path, timeout=fs._LOCK_TIMEOUT_SEC):
            d = getattr(depth, "d", 0) + 1
            depth.d = d
            observed.append(d)
            return real_acquire(path, timeout)

        def _release(fd, lock_path):
            depth.d = getattr(depth, "d", 0) - 1
            real_release(fd, lock_path)

        monkeypatch.setattr(fs, "_acquire_lock", _acquire)
        monkeypatch.setattr(fs, "_release_lock", _release)

        save_feed(project_path, make_feed(3, project_name="test-project"))
        append_feed_card(project_path, make_card("diff", card_id="nn-1"))
        update_feed_card(project_path, "perf-0", {"accepted": True})
        fs.compact_feed(project_path)
        load_feed(project_path)

        assert observed, "no lock acquisitions observed"
        assert max(observed) == 1, f"nested acquire observed: {observed}"


class TestSerializationGuards:
    """Invariant 6 — never a corrupt write, never a crash."""

    def test_non_json_native_value_falls_back_and_never_corrupts(
        self, project_path, caplog
    ):
        save_feed(project_path, [make_card("diff", card_id="ser-1")])
        feed_before = open(fs._feed_path(project_path), encoding="utf-8").read()

        class NotJsonNative:
            pass

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            # An ignored key carrying a non-serializable value: the journal
            # cannot dump it, so the legacy path runs — and the card's
            # serialized form is still written correctly.
            result = update_feed_card(
                project_path, "ser-1", {"not_a_field": NotJsonNative()}
            )

        assert result is True, "legacy fallback must complete the write"
        assert any(
            r.levelno == logging.WARNING for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
        # feed.json is valid JSON, not a half-written file.
        raw = json.load(open(fs._feed_path(project_path), encoding="utf-8"))
        assert raw[0]["card_id"] == "ser-1"

    def test_non_serializable_allowed_field_never_crashes(
        self, project_path, caplog
    ):
        """An allowed field carrying garbage: logged False, file intact."""
        save_feed(project_path, [make_card("diff", card_id="ser-2")])
        feed_before = open(fs._feed_path(project_path), encoding="utf-8").read()

        class NotJsonNative:
            pass

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            result = update_feed_card(
                project_path, "ser-2", {"accepted": NotJsonNative()}
            )

        assert result is False, "must report a write failure, not crash"
        assert open(fs._feed_path(project_path), encoding="utf-8").read() == feed_before

    def test_journal_skips_non_dict_metadata_with_warning(self, project_path, caplog):
        save_feed(project_path, [make_card("diff", card_id="nj-1")])

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            ok = fs.append_card_update(
                project_path, "nj-1", {"accepted": True, "metadata": "not-a-dict"}
            )

        assert ok is True, "the record is still written (sans metadata)"
        assert any("metadata" in r.getMessage() for r in caplog.records)
        loaded = load_feed(project_path)
        assert loaded[0].accepted is True, "the sibling key still applied"
        record = json.loads(_journal_lines(project_path)[0])
        assert "metadata" not in record["updates"]

    def test_overlay_skips_non_dict_metadata_with_warning(self, project_path, caplog):
        save_feed(project_path, [
            make_card("diff", card_id="nj-2", metadata={"keep": 1}),
        ])
        cards = load_feed(project_path)

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            fs._apply_overlay(cards, {"nj-2": {"metadata": "garbage"}})

        assert cards[0].metadata == {"keep": 1}, "metadata must be left intact"
        assert any("metadata" in r.getMessage() for r in caplog.records)


class TestCompactionFailure:
    """Invariant 7 — append success stands regardless of compaction."""

    def test_true_despite_compact_failure_and_no_duplicate_lines(
        self, project_path, monkeypatch, caplog
    ):
        save_feed(project_path, [make_card("diff", card_id="cf-1")])
        monkeypatch.setattr(
            fs, "_journal_line_count", lambda p: fs.JOURNAL_COMPACT_THRESHOLD
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("compact exploded")

        monkeypatch.setattr(fs, "compact_feed", _boom)

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            result = update_feed_card(project_path, "cf-1", {"accepted": True})

        assert result is True, "the journal line is durable → True stands"
        assert any(
            "compaction failed" in r.getMessage() for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
        assert len(_journal_lines(project_path)) == 1, (
            "a compact failure must never duplicate the journal line"
        )


class TestCompactRateLimit:
    """Invariant 9 / E9 — at most one append-triggered compact per 60 s."""

    def test_two_triggers_within_interval_compact_once(self, project_path, monkeypatch):
        save_feed(project_path, make_feed(2600, project_name="test-project"))
        fs._compact_last.pop(project_path, None)
        calls = []
        monkeypatch.setattr(
            fs, "compact_feed", lambda p, window=None: calls.append((p, window)) or 0
        )

        fs._maybe_compact(project_path)
        fs._maybe_compact(project_path)

        assert len(calls) == 1, f"expected one compact, got {calls}"

    def test_timestamp_recorded_before_size_check(self, project_path, monkeypatch):
        """A sub-window feed still spends the interval (prevents re-check thrash)."""
        save_feed(project_path, make_feed(10, project_name="test-project"))
        fs._compact_last.pop(project_path, None)
        calls = []
        monkeypatch.setattr(
            fs, "compact_feed", lambda p, window=None: calls.append(p) or 0
        )

        fs._maybe_compact(project_path)

        assert calls == [], "feed under the bound → no compaction"
        assert fs._compact_last.get(project_path) is not None

    def test_append_feed_card_triggers_compaction_check(self, project_path, monkeypatch):
        save_feed(project_path, make_feed(2600, project_name="test-project"))
        fs._compact_last.pop(project_path, None)
        calls = []
        monkeypatch.setattr(
            fs, "compact_feed", lambda p, window=None: calls.append(p) or 0
        )

        append_feed_card(project_path, make_card("diff", card_id="app-1"))

        assert len(calls) == 1, "append path must run the rate-limited trigger"

    def test_maybe_compact_noops_without_feed_file(self, project_path):
        fs._compact_last.pop(project_path, None)
        fs._maybe_compact(project_path)  # must not raise
        assert project_path not in fs._compact_last


# ═══════════════════════════════════════════════════════════════════
#  Phase-2 send-back — ONE lock inode for every mutation (spec §2.2.3:
#  "every feed_store mutation (snapshot or journal) holds the feed
#  flock"). Red-first: both tests FAIL against the split-lock tree,
#  where the journal writer took `_acquire_lock(journal_path)` — a
#  different inode from every other mutation's feed flock.
# ═══════════════════════════════════════════════════════════════════


class TestSingleLockInode:
    """Debugger-confirmed CRITICAL: the journal must contend on the FEED lock.

    `fcntl.flock` is per-inode, so `.crabcakes/feed-updates.jsonl.lock` and
    `.crabcakes/feed.json.lock` provide NO mutual exclusion. Under the split
    lock an append could report True and still be swallowed by a concurrent
    compaction's fold+truncate (lost despite success). These tests pin the
    uniform rule: one lock inode — the feed path — for every mutation.
    """

    def test_journal_append_and_compaction_share_one_lock_inode(
        self, project_path, caplog
    ):
        import fcntl
        import logging

        save_feed(project_path, [make_card("diff", card_id="sl-1")])

        # Hold the FEED lock externally — the same lock compact_feed and every
        # other mutation takes (raw flock, the TestBoundedLock pattern).
        feed_lock = fs._feed_path(project_path) + ".lock"
        held_fd = os.open(feed_lock, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
                result = fs.append_card_update(
                    project_path, "sl-1", {"accepted": True}
                )
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            os.close(held_fd)

        assert result is False, (
            "the journal append must contend on the FEED lock; returning True "
            "here means it took a different lock inode (split-lock bug)"
        )
        assert _journal_lines(project_path) == [], (
            "no update may be recorded while the feed lock is held"
        )
        assert any("feed lock" in r.getMessage() for r in caplog.records), (
            [r.getMessage() for r in caplog.records]
        )

    def test_no_update_lost_when_append_interleaves_compaction(
        self, project_path, monkeypatch
    ):
        """No update is silently lost when an append interleaves compaction.

        Deterministic interleave — the writer's append lands inside compact's
        fold window (after compact read the journal, before its truncate):
        exactly the window the split lock opened. The invariant pinned is
        "no silent loss," asserted via two branches: on the BROKEN tree the
        hook's append succeeds (True) and the fold+truncate swallows it —
        that branch is the load-bearing regression catch; on the FIXED tree
        the in-process append cannot take a lock other than the one
        compaction holds, so it reports False and the Phase-1 writer's
        deferred retry records it instead. (The stronger "True-means-
        durable" property is structurally unreachable in-process here — it
        would need cross-process locking to exercise.)
        """
        save_feed(project_path, [make_card("diff", card_id="il-1")])
        real_replay = fs._replay_journal
        appended: dict[str, bool] = {}

        def _interleaving_replay(p):
            overlay = real_replay(p)          # fold the pre-writer journal
            appended["ok"] = fs.append_card_update(
                p, "il-1", {"body": "landed-mid-fold"}
            )
            return overlay

        monkeypatch.setattr(fs, "_replay_journal", _interleaving_replay)
        fs.compact_feed(project_path)
        monkeypatch.undo()                    # post-checks use the real reader

        assert "ok" in appended, "the interleave hook never ran — test invalid"
        if appended["ok"] is True:
            assert load_feed(project_path)[0].body == "landed-mid-fold", (
                "append reported True but the fold+truncate swallowed it — "
                "silent loss (split-lock)"
            )
        else:
            assert appended["ok"] is False, appended
            # The writer defers on False and retries (3 attempts): simulate
            # that retry now that compaction has released the lock.
            assert fs.append_card_update(
                project_path, "il-1", {"body": "landed-mid-fold"}
            ) is True
            assert load_feed(project_path)[0].body == "landed-mid-fold"


# ═══════════════════════════════════════════════════════════════════
#  SPEC-UI-RESPONSIVENESS-2 Phase 3 — sliding-window pruning (§2.3.2).
#  Red-first: tests 1, 2 and 4 prune nothing against the Phase-2 tree
#  (`window` was accepted but ignored). Tests 3 and 5 are regression /
#  edge guards for the retained `window=None` path — green both sides.
# ═══════════════════════════════════════════════════════════════════

_WINDOW = 5


class TestWindowPruning:
    """§2.3.2 retention rules — pins, count, logging, window=None path."""

    def test_pins_survive_pruning_beyond_window(self, project_path):
        """Every pinned class outside the newest `window` slice is kept."""
        cards = [
            # Oldest — one card of each pinned class, plus one pruneable.
            make_card("diff", card_id="pin-accepted", accepted=True),
            make_card("diff", card_id="pin-review",
                      metadata={"needs_review": True}),
            make_card("diff", card_id="pin-approval",
                      metadata={"needs_approval": True}),
            make_card("git_commit", card_id="pin-git"),
            make_card("diff", card_id="prune-me"),
        ] + [
            make_card("diff", card_id=f"new-{i}") for i in range(_WINDOW)
        ]
        save_feed(project_path, cards)

        pruned = fs.compact_feed(project_path, window=_WINDOW)

        ids = [c.card_id for c in load_feed(project_path)]
        assert pruned == 1, f"exactly the unpinned old card prunes: {ids}"
        for pinned in ("pin-accepted", "pin-review", "pin-approval", "pin-git"):
            assert pinned in ids, f"{pinned} is pinned and must survive"
        assert "prune-me" not in ids
        assert [f"new-{i}" for i in range(_WINDOW)] == [
            i for i in ids if i.startswith("new-")
        ], "the newest window is retained in order"

    def test_seq_num_max_survives_compaction(self, project_path):
        """Invariant 2 — seq numbering stays monotonic across compaction."""
        cards = [
            make_card("diff", card_id=f"sq-{i}", seq_num=i + 1)
            for i in range(6)
        ]
        save_feed(project_path, cards)

        fs.compact_feed(project_path, window=2)

        loaded = load_feed(project_path)
        assert len(loaded) == 2, "the window must actually prune (else untested)"
        seqs = [c.seq_num for c in loaded]
        assert max(seqs) == 6, "the highest seq must survive the prune"
        assert len(set(seqs)) == len(seqs), "no duplicate seq numbers"

    def test_window_none_prunes_nothing(self, project_path):
        """Regression guard: the Phase-2 no-window path stays intact."""
        save_feed(project_path, make_feed(10))

        assert fs.compact_feed(project_path, window=None) == 0
        assert len(load_feed(project_path)) == 10

    def test_pruned_count_returned_and_warning_logs_pinned_count(
        self, project_path, caplog
    ):
        cards = [
            make_card("git_commit", card_id="w-git"),
            make_card("diff", card_id="w-plain-1"),
            make_card("diff", card_id="w-plain-2"),
        ] + [make_card("diff", card_id=f"w-new-{i}") for i in range(2)]
        save_feed(project_path, cards)

        with caplog.at_level(logging.WARNING, logger="utils.feed_store"):
            pruned = fs.compact_feed(project_path, window=2)

        assert pruned == 2, "two unpinned cards fall outside the window"
        assert any("pinned" in r.getMessage() for r in caplog.records), (
            [r.getMessage() for r in caplog.records]
        )

    def test_all_cards_pinned_prunes_zero(self, project_path):
        """Edge: everything pinned → prune count 0, nothing lost."""
        save_feed(project_path, [
            make_card("git_commit", card_id=f"ap-{i}") for i in range(10)
        ])

        assert fs.compact_feed(project_path, window=2) == 0
        assert len(load_feed(project_path)) == 10

    def test_load_feed_under_100ms_at_window_default(self, project_path):
        """Spec §6 / Phase-3 invariant 4: after one-time compaction of a
        9,500-card feed, load_feed at the window default stays <100 ms.

        Structural companion (§9 timing discipline): the loaded count must
        equal the window exactly, so a timing flake can never mask a
        functional break."""
        import time as _time
        cards = make_feed(9500)
        save_feed(project_path, cards)

        fs.compact_feed(project_path, window=fs.FEED_WINDOW_DEFAULT)

        t0 = _time.perf_counter()
        loaded = load_feed(project_path)
        elapsed_ms = (_time.perf_counter() - t0) * 1000.0

        assert len(loaded) == fs.FEED_WINDOW_DEFAULT, (
            f"expected exactly the window after compaction, got {len(loaded)}"
        )
        assert elapsed_ms < 100.0, (
            f"load_feed took {elapsed_ms:.1f} ms at the window default "
            f"(spec §6 bound: 100 ms)"
        )
