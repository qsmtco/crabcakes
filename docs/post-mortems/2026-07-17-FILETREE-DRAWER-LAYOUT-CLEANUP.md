**Task:** Fix BUG #1 — duplicate attribute-init block in FileTreeRowWidget.__init__
**File:** ui/views/file_tree.py
**Severity:** LOW (idempotent, but latent maintenance trap)
**Bug:** Lines 114-119 duplicated lines 107-112 — same two attribute assignments (self._bound_row and self._expander_handler_id) appeared twice in a row in __init__.
**Expected:** Each instance attribute assigned exactly once.
**Actual:** Duplicate block. Functionally harmless (idempotent) but misleading and a maintenance trap.
**Root cause:** Commit f92a75a appended a 5-line block that was already present 4 lines above.
**Fix:** Deleted the second copy (6 lines: comment + 2 assignments + blank line + comment + 2 assignments → reduced to just the comment header).
**Pattern:** over-fixing
**Tests:** Syntax check passes. Import works. No new tests needed — removal of duplicate code cannot break behavior.