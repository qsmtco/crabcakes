# PHASE 10 — P5: Settings Dialog Read-Only Caller Label

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.6 of the master spec

---

## Files to change

1. `ui/views/settings_dialog.py` — three targeted edits in `_ProviderCard`

## What to do

**In `ui/views/settings_dialog.py`:**

**Edit 1 — Update the placeholder ProviderConfig construction (line 37-38):**

Find:
```python
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key="", default_model="",
        )
```

Replace with:
```python
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key="", default_model="", caller="",
        )
```

**Edit 2 — Add the caller label widget in `_build_widgets` (after the api_key_row vbox.append):**

Find this in `_build_widgets` (around line 91):
```python
        vbox.append(api_key_row)
        # Status label
```

Add BEFORE the `# Status label` comment:
```python
        # Read-only caller label — shows the resolved API caller (openai|minimax|...).
        # Caller is auto-detected by settings_handler.add_or_update when saving.
        self._caller_label = Gtk.Label()
        self._caller_label.set_xalign(0.0)
        self._caller_label.add_css_class("dim-label")
        caller_row = self._labeled("Caller", self._caller_label)
        vbox.append(caller_row)

        # Status label
```

**Edit 3 — Populate the caller label in `_populate_from_provider` (after the api_key line):**

Find in `_populate_from_provider` (around line 138):
```python
        self._api_key_entry.set_text(p.api_key or "")
```

Add AFTER it:
```python
        self._caller_label.set_text(
            f"  {p.caller}" if p.caller else "  (auto-detected on save)"
        )
```

**Edit 4 — Preserve caller in `_collect_from_form` (add caller=existing.caller):**

Find in `_collect_from_form` (around line 170-171):
```python
            default_model=self._model_entry.get_text().strip(),
            enabled=existing.enabled if existing else True,
```

Add BEFORE `enabled`:
```python
            default_model=self._model_entry.get_text().strip(),
            caller=existing.caller if existing else "",
            enabled=existing.enabled if existing else True,
```

**Why Edit 4 matters:** when the user edits a provider (e.g. fixes the API key), `_collect_from_form` is called. Without `caller=existing.caller`, the caller would be silently cleared to `""` and lost on next save. With this line, the caller is preserved across edits.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `ui/views/settings_dialog.py` lines 30-55, 85-115, 130-180 COMPLETELY before editing
- Make ONLY the 4 edits described above
- Do NOT add any Entry widget for caller — it is read-only
- Do NOT touch `settings_handler.py`
- Do NOT touch `_on_test_clicked` (that's P6)
- Do NOT touch the `_labeled` helper method

## Verification (mandatory — paste full output)

Run BOTH and paste full output:

```bash
cd /home/q/projects/crabcakes
python3 -c "
from ui.views.settings_dialog import _ProviderCard
from models.providers import ProviderConfig
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
# Verify: placeholder ProviderConfig has caller=''
# (check the __init__ source)
import inspect
src = inspect.getsource(_ProviderCard.__init__)
assert 'caller=\"\"' in src, 'caller=\"\" not found in _ProviderCard.__init__ source'
# Verify: _populate_from_provider sets caller label
src2 = inspect.getsource(_ProviderCard._populate_from_provider)
assert '_caller_label.set_text' in src2, '_caller_label.set_text not found'
print('P5 source checks: placeholder caller=\"\" OK, caller_label set_text OK')
"
```

```bash
cd /home/q/projects/crabcakes
grep -n "_caller_label\|caller=" ui/views/settings_dialog.py | head -15
```

Expected: at least 5 matches (placeholder, label widget, label set_text in populate, label reference in dirty check, caller= in collect).

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_settings_dialog.py -q 2>&1 | tail -6
```

If `test_settings_dialog.py` doesn't exist:
```bash
ls /home/q/projects/crabcakes/tests/ | grep -i settings
```

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output (or list of test files found)
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.