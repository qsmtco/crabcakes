# tests/test_review_state.py
# Tests for models/review_state.py

import pytest
from models.review_state import ReviewState


class TestReviewState:
    def test_default_values(self):
        state = ReviewState(project_path="/path/to/project")
        assert state.project_path == "/path/to/project"
        assert state.review_mode == "off"
        assert state.checkpoint_sha is None
        assert state.is_dirty is False
        assert state.last_check_files == []

    def test_is_active_true(self):
        state = ReviewState(project_path="/path/to/project", checkpoint_sha="abc123")
        assert state.is_active() is True

    def test_is_active_false_no_checkpoint(self):
        state = ReviewState(project_path="/path/to/project")
        assert state.is_active() is False

    def test_can_checkpoint_off_mode(self):
        state = ReviewState(project_path="/path/to/project", review_mode="off")
        assert state.can_checkpoint() is False

    def test_can_checkpoint_review_mode_no_checkpoint(self):
        state = ReviewState(project_path="/path/to/project", review_mode="review")
        assert state.can_checkpoint() is True

    def test_can_checkpoint_review_mode_with_checkpoint(self):
        state = ReviewState(project_path="/path/to/project", review_mode="review", checkpoint_sha="abc123")
        assert state.can_checkpoint() is False

    def test_is_dirty_flag(self):
        state = ReviewState(project_path="/path/to/project", is_dirty=True)
        assert state.is_dirty is True

    def test_last_check_files(self):
        files = ["src/main.py", "src/utils.py"]
        state = ReviewState(project_path="/path/to/project", last_check_files=files)
        assert state.last_check_files == ["src/main.py", "src/utils.py"]

    def test_review_mode_values(self):
        state_off = ReviewState(project_path="/p", review_mode="off")
        state_review = ReviewState(project_path="/p", review_mode="review")
        assert state_off.review_mode == "off"
        assert state_review.review_mode == "review"

    def test_checkpoint_sha_tracking(self):
        state = ReviewState(project_path="/path/to/project")
        assert state.checkpoint_sha is None
        # Simulate setting checkpoint
        state.checkpoint_sha = "def4567890abcdef"
        assert state.is_active() is True
        assert state.checkpoint_sha == "def4567890abcdef"

    def test_multiple_projects_independent(self):
        state1 = ReviewState(project_path="/project1", review_mode="review")
        state2 = ReviewState(project_path="/project2", review_mode="off")
        assert state1.review_mode == "review"
        assert state2.review_mode == "off"
        assert state1.can_checkpoint() is True
        assert state2.can_checkpoint() is False
