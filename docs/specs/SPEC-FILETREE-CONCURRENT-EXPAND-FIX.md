# SPEC: File Tree Concurrent-Expand Fix

**Date:** 2026-08-14
**Status:** Approved for implementation
**Authority:** This spec narrows `docs/ARCHITECTURE.md` for one bug fix. It does not
override any architectural rule. Handler/view separation is unchanged — all edits
stay inside the existing view `ui/views/file_tree.py`.

---

## 1. Problem

User report: opening the `eagledispatch` project in CrabCakes shows the File Tree
tab with folders **expanded but empty**. Not all folders in the project appear.
Intermittent — depends on click timing.

## 2. Root Cause (verified by reproduction, 2026-08-14)

`ui/views/file_tree.py` uses a **single global request counter**
(`self._current_request_id`) as its stale-async-callback guard:

- `_expand_directory()` (~line 1978): increments the global counter, captures it
  in the closure, passes it to `_on_directory_loaded`.
- `_on_directory_loaded()` (~line 2031): `if request_id != self._current_request_id: return`
- `_collapse_directory()` (~line 2087): increments the same global counter.
- `_clear_all_state()` (~line 603): increments the same global counter.

Because the guard is **global**, ANY subsequent expand, collapse, or state-clear
invalidates ALL in-flight directory loads — not just the one it should.

**Reproduced:** load eagledispatch → expand `apps` then `packages` back-to-back
(before background scans complete) → `apps` shows `[EXPANDED]` with **zero
children**; only `packages` receives its children. Only the most recent
expansion's load survives the guard.

Directory scans run on a background thread (`threading.Thread` +
`GLib.idle_add`), so any second click that lands inside the scan window silently
discards the first load. The row is already marked `expanded=True`, so the user
sees an empty folder with no way to reload it short of collapse/re-expand.

## 3. Fix Design

Replace the global counter with **per-parent request tokens**.

### 3.1 State

Replace:
```python
self._current_request_id = 0  # For async guard (BUG #7)
```
with:
```python
# Per-parent async load tokens: parent full_path -> latest request id.
# Only the newest load for a given directory may insert children.
self._dir_load_requests: dict[str, int] = {}
```

### 3.2 `_expand_directory`

Replace the global bump:
```python
self._current_request_id += 1
request_id = self._current_request_id
```
with:
```python
parent_path = row.props.full_path
self._dir_load_requests[parent_path] = self._dir_load_requests.get(parent_path, 0) + 1
request_id = self._dir_load_requests[parent_path]
```
(Note: `parent_path` is already computed below in the current code as
`parent_path = row.props.full_path` — reuse/merge; do not compute twice.)

### 3.3 `_on_directory_loaded`

Replace:
```python
if request_id != self._current_request_id:
    return
```
with:
```python
if self._dir_load_requests.get(parent_row_obj.props.full_path) != request_id:
    return
```
All other guards in `_on_directory_loaded` (loading-row removal by object
identity, parent re-find by object identity, `parent.props.expanded` check)
remain unchanged — they are correct and complementary.

### 3.4 `_collapse_directory`

Remove the `self._current_request_id += 1` line. **Do NOT touch the token dict
on collapse.** The `expanded=False` check in `_on_directory_loaded` already
discards loads for a collapsed parent, and leaving the token in place means a
collapse→re-expand cycle bumps to a fresh token, discarding the older in-flight
load. Bumping or popping on collapse would be incorrect:
- pop → re-expand starts from 1 again, and a stale same-numbered load would
  wrongly pass the check and insert duplicate children.
- bump → harmless but unnecessary; expand is the only operation that mints
  tokens.

### 3.5 `_clear_all_state`

Replace:
```python
# Invalidate any in-flight async requests
self._current_request_id += 1
```
with:
```python
# Invalidate any in-flight async requests (per-parent tokens)
self._dir_load_requests.clear()
```
In-flight loads then fail the §3.3 check (`get()` → `None != request_id`).

### 3.6 Why both guards (token + `expanded` check) are required

| Scenario | Token check | `expanded` check |
|---|---|---|
| Expand A, expand B while A in flight | A's token still valid → A inserts ✓ | — |
| Expand A, collapse A before load | — | `expanded=False` → discard ✓ |
| Expand A, collapse A, re-expand A before first load returns | token bumped on re-expand → stale load discarded ✓ (prevents duplicate children) | — |

## 4. Acceptance Criteria

1. Expanding two (or more) directories in rapid succession results in **all**
   of them receiving their children.
2. Expand → collapse → re-expand before the first scan returns produces exactly
   one set of children (no duplicates).
3. Project switch / navigate-back while scans are in flight discards those
   scans (no children leak into the new project's tree).
4. `grep -c "_current_request_id" ui/views/file_tree.py` returns **0**.
5. No behavior change for single-directory expand/collapse flows.
6. Hot-loop check: token dict operations are O(1) per expand/collapse/scan-
   completion (user-action frequency, not per-frame).

## 5. Files in Scope

| File | Change |
|---|---|
| `ui/views/file_tree.py` | §3.1–3.5 (5 edit sites) |
| `tests/test_file_tree_columnview.py` | New regression tests (Phase 2) |

Nothing else. No handler changes, no `utils/projects.py` changes (scan layer
verified complete), no ARCHITECTURE.md changes (no new conventions).

## 6. Test Plan (Phase 2)

Deterministic tests — no real timing. Patch `GLib.idle_add` to capture
callbacks and invoke them manually, and patch `scan_directory` with a
controllable fake.

1. `test_concurrent_expand_all_dirs_receive_children` — expand A then B before
   either scan returns; release both scans; assert both have children.
   **This test must fail on the pre-fix code** (verify with `git stash`).
2. `test_collapse_reexpand_no_duplicate_children` — expand A, collapse A,
   re-expand A, deliver both loads; assert children appear exactly once.
3. `test_clear_state_discards_inflight_load` — expand A, clear state, deliver
   load; assert no rows inserted.
4. Existing suite: `python3 -m pytest tests/test_file_tree_columnview.py -v`
   must show no regressions (known environmental segfault on
   `TestFileTreeRowWidget::test_widget_creation` in headless sandboxes — run
   under `xvfb-run -a` where GTK requires a display).
