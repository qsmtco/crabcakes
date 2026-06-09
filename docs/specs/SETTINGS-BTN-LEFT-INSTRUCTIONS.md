# SETTINGS-BTN-LEFT — Move Settings button to the left of the toolbar

## Master spec
This file (single-deliverable spec).

## Goal

In the top toolbar, move the `⚙ Settings` button from the right-aligned cluster (`[ status | Settings | Connect ]`) to the left side, immediately to the **right of the Stream toggle**. The new layout reads:

```
[ Stream | ⚙ Settings ]  ←—expanding spacer—→  [ status | Connect ]
```

## Files to change

1. `ui/toolbar.py` — REVISED. Only the `__init__` body changes. No new public methods, no removed methods, no API changes. Net line change: roughly even (a few lines added for `left_box`, one line removed from `right_box`).

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT modify any other file.** This is a focused layout change in one file. Tests must continue to pass without modification.
- **Do NOT change the public API of `Toolbar`.** Constructor signature, `update_connection_state()`, `set_settings_status()` all stay exactly the same.
- **Preserve all instance attributes:** `self._stream_btn`, `self._connect_btn`, `self._status_label`, `self._settings_btn`, `self._status_dot` must all still exist on the constructed Toolbar.
- **Preserve the red-dot overlay:** the settings button must remain wrapped in a `Gtk.Overlay` so `set_settings_status()` can show/hide the dot.
- **Preserve the expanding spacer** that pushes the right cluster to the far right.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `ui/toolbar.py` — full file (read every line before editing)
2. `tests/test_toolbar.py` — full file (verify no test asserts on widget order)
3. `docs/ARCHITECTURE.md` §3.4 — confirm the public API contract for `Toolbar`

Output a `DISCOVERY:` block listing each file read and what you learned.

## Change plan

### Change 1: Build a `left_box` containing Stream + Settings

In `__init__`, after `self._stream_btn` is created and the settings button + overlay + status dot are built (currently around lines 51–66 of the file), add:

```python
# Left cluster: Stream toggle + Settings button (the expanding spacer
# pushes everything to the right of this cluster to the far right edge).
left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
left_box.append(self._stream_btn)
left_box.append(overlay)   # overlay wraps self._settings_btn + self._status_dot
```

### Change 2: Remove settings from `right_box`

In the `right_box.append(...)` calls, delete the `right_box.append(overlay)` line so `right_box` only contains the status label and the Connect button. `right_box` becomes:

```python
right_box.set_spacing(6)
right_box.append(self._status_label)
right_box.append(self._connect_btn)
```

### Change 3: Update the final assembly order

Replace the final three `self.append(...)` calls at the bottom of `__init__`:

```python
# Assemble: stream btn | spacer | right content
self.append(self._stream_btn)
self.append(spacer)
self.append(right_box)
```

with:

```python
# Assemble: [Stream | Settings] | expanding spacer | [status | Connect]
self.append(left_box)
self.append(spacer)
self.append(right_box)
```

That's it. No other lines change. No CSS, no styles, no callbacks, no window.py edits.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# Imports ok
python3 -c "from ui.toolbar import Toolbar; print('imports ok')"
echo "---"

# Toolbar still has all expected attributes
python3 -c "
from ui.toolbar import Toolbar
t = Toolbar()
for attr in ['_stream_btn','_settings_btn','_status_dot','_connect_btn','_status_label']:
    assert hasattr(t, attr), f'missing {attr}'
print('all attributes present')
"
echo "---"

# Existing toolbar tests pass
python3 -m pytest tests/test_toolbar.py -v --tb=short 2>&1 | tail -20
echo "---"

# Full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

## Acceptance criteria

- [ ] `self._stream_btn`, `self._settings_btn`, `self._status_dot`, `self._connect_btn`, `self._status_label` all exist after construction
- [ ] `tests/test_toolbar.py` still passes (all 12 tests, no modifications to the test file)
- [ ] Full test suite passes
- [ ] Public API of `Toolbar` unchanged: `__init__(on_connect_clicked, *, on_settings_clicked)`, `update_connection_state(state)`, `set_settings_status(has_verified_provider)` all still present with the same signatures
- [ ] Settings button is wrapped in a `Gtk.Overlay` with the status dot (so the red dot still works)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
SETTINGS-BTN-LEFT — COMPLETE

Files changed:
- ui/toolbar.py — REVISED, +N / -M lines (paste git diff --stat)

Verification (paste outputs):
- imports ok: ...
- all attributes present: ...
- test_toolbar.py: ...
- full suite: ...

**COMPLETENESS:**
- [x] Edit 1: left_box built with Stream + Settings — evidence: <paste final self.append block + line numbers>
- [x] Edit 2: overlay removed from right_box — evidence: <grep right_box.append\(overlay\) → 0 matches>
- [x] Edit 3: assembly order updated — evidence: <paste the 3 self.append lines>
- [x] All five instance attributes preserved — evidence: <paste attribute check output>
- [x] tests/test_toolbar.py passes unchanged — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <pytest tail>

**Implementation choices made:**
- (e.g. "kept `right_box` rather than inlining status + connect, to minimize diff and preserve spacing logic")
- (list any other non-obvious choices with one-sentence rationale)

**Notes for the spec maintainer:**
- (any deviation from this spec and the reason)

When done, please write: `Settings-btn-left complete — all checks pass.`
```

When done, please write: `Settings-btn-left complete — all checks pass.`
