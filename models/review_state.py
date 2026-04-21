# models/review_state.py
# Per-project review session state. Pure data class — no GTK, no git calls, no network.
#
# One instance per open project tab, stored in ReviewHandler._states: dict[str, ReviewState]
# keyed by project_name.

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReviewState:
    """Per-project review session state. One instance per open project tab."""
    project_path: str                       # absolute path to project directory
    review_mode: str = "off"                 # "off" | "review"
    checkpoint_sha: Optional[str] = None     # git SHA at last checkpoint (None = no active session)
    is_dirty: bool = False                  # True if files changed since checkpoint
    last_check_files: list[str] = field(default_factory=list)  # files changed at last check

    def is_active(self) -> bool:
        """True if a review session is in progress (checkpoint taken, not yet resolved)."""
        return self.checkpoint_sha is not None

    def can_checkpoint(self) -> bool:
        """True if review mode is on and no active session (can start a new one)."""
        return self.review_mode == "review" and self.checkpoint_sha is None
