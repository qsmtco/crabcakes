# Plan: Audit Fixes — StreamingBubble Dataclass, Config Module, Test Verification

**Author:** Qaster
**Date:** 2026-04-13
**Status:** Draft
**Addresses:** CODE_AUDIT.md issues #6 (positional tuple), #4 (config duplication), #9 (test verification)

---

## Overview

Three targeted fixes from QTR's code audit. Each is independent and can be verified separately.

---

## Fix A: Replace StreamingBubble Positional Tuple with Dataclass (#6)

### Problem

`_streaming_bubbles` stores 5-element tuples accessed by position:

```python
self._streaming_bubbles[session_key] = (container, label, role, "", bubble)
container, label, role, _old_plain, _bubble = self._streaming_bubbles[session_key]
```

Adding a sixth field requires updating every unpack site. Easy to introduce off-by-one bugs.

### Solution

Replace with a `dataclass` in `models/`.

### Step A1: Create `models/streaming.py`

```python
# models/streaming.py — Streaming bubble state
#
# Manifest: reads nothing, writes nothing, no network
# Pure data container for streaming bubble lifecycle state.

from dataclasses import dataclass, field
from gi.repository import Gtk


@dataclass
class StreamingBubble:
    """Tracks state for an in-progress streaming response bubble.

    Stored in ChatRenderHandler._streaming_bubbles dict, keyed by session_key.
    """
    container: object     # chat box (Gtk.Box or FakeChatBox in tests)
    label: object         # Gtk.Label inside the streaming bubble
    role: str             # "Agent" or "You"
    plain_text: str = ""  # accumulated plain text (last delta)
    bubble: object = None # the streaming bubble widget
```

**Wait** — `models/` rule says no GTK imports. But this dataclass only uses `object` type hints for the GTK widgets (no actual GTK imports). Verified: no `gi.repository` import needed. Pure data.

### Step A2: Update `models/__init__.py`

Add export:
```python
from .streaming import StreamingBubble
```

### Step A3: Update `ChatRenderHandler`

In `ui/handlers/chat_render_handler.py`:

| Old | New |
|-----|-----|
| `self._streaming_bubbles[sk] = (container, label, role, "", bubble)` | `self._streaming_bubbles[sk] = StreamingBubble(container=container, label=label, role=role, bubble=bubble)` |
| `container, label, role, _old_plain, _bubble = self._streaming_bubbles[sk]` | `sb = self._streaming_bubbles[sk]` then `sb.container`, `sb.label`, etc. |
| `self._streaming_bubbles[sk] = (container, label, role, delta_text, _bubble)` | `sb.plain_text = delta_text` (mutate in-place, no tuple rebuild) |
| `container, label, role, plain, streaming_bubble = self._streaming_bubbles.pop(sk)` | `sb = self._streaming_bubbles.pop(sk)` then `sb.container`, `sb.plain_text`, etc. |

This eliminates ALL positional access. Adding a new field is just adding a dataclass attribute.

### Step A4: Update ARCHITECTURE.md

- Section 2: Add `streaming.py` under `models/`
- Section 3: Add new §3.x for `models/streaming.py` with public API
- Section 12: Add to file inventory

### Step A5: Tests

Existing `TestPhase3Streaming` tests in `test_chat_render_handler.py` should pass unchanged — they access streaming state through the handler's public API, not the tuple directly. Verify with `pytest`.

Create `tests/test_streaming.py` — unit tests for the `StreamingBubble` dataclass:
- Default `plain_text` is `""`
- Default `bubble` is `None`
- Can set all fields
- Can mutate `plain_text` in-place

### Verification

- [ ] `python3 -m py_compile models/streaming.py`
- [ ] `pytest tests/test_chat_render_handler.py` — all Phase 3 streaming tests pass
- [ ] `pytest tests/test_streaming.py` — dataclass tests pass
- [ ] `pytest` full suite — no regressions

---

## Fix B: Centralize Config Path Resolution (#4)

### Problem

Three files resolve config paths independently:

| File | Path | Pattern |
|------|------|---------|
| `utils/improve.py` | `~/.config/crabcakes/config.json` | `os.path.expanduser("~/.config/crabcakes/...")` |
| `gateway/client.py` | `~/.openclaw/identity/` | `os.path.expanduser("~/.openclaw/identity/")` |
| `utils/projects.py` | `~/.config/crabcakes/projects/` | `os.path.expanduser("~/.config/crabcakes/projects/...")` |

No shared module. If config location changes (e.g., `$XDG_CONFIG_HOME`), every file needs updating.

### Solution

Create `utils/config.py` with path helper functions. Each existing file calls the helper instead of computing paths directly.

### Step B1: Create `utils/config.py`

```python
# utils/config.py — Centralized configuration path resolution
#
# Manifest: reads environment variables only, no file I/O, no network
# Single source of truth for all config and data directory paths.

import os


def get_config_dir() -> str:
    """Return the CrabCakes config directory.
    
    Respects $XDG_CONFIG_HOME if set, otherwise ~/.config/crabcakes.
    Does NOT create the directory.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "crabcakes")


def get_config_file() -> str:
    """Return path to config.json."""
    return os.path.join(get_config_dir(), "config.json")


def get_projects_config_dir() -> str:
    """Return path to projects config directory (members.json files)."""
    return os.path.join(get_config_dir(), "projects")


def get_projects_dir() -> str:
    """Return the projects directory (actual project folders to browse).
    
    Controlled by $CRABCAKES_PROJECTS_DIR, defaults to ~/projects.
    """
    return os.environ.get("CRABCAKES_PROJECTS_DIR", os.path.expanduser("~/projects"))


def get_gateway_url() -> str:
    """Return the gateway WebSocket URL.
    
    Controlled by $CRABCAKES_GATEWAY_URL, defaults to ws://localhost:18789.
    """
    return os.environ.get("CRABCAKES_GATEWAY_URL", "ws://localhost:18789")


def get_identity_dir() -> str:
    """Return the OpenClaw device identity directory."""
    return os.path.join(os.path.expanduser("~"), ".openclaw", "identity")
```

### Step B2: Update `utils/improve.py`

Replace:
```python
path = os.path.join(os.path.expanduser("~/.config/crabcakes/config.json"))
```
With:
```python
from utils.config import get_config_file
path = get_config_file()
```

### Step B3: Update `utils/projects.py`

Replace `PROJECTS_DIR` env var reading and `~/.config/crabcakes/projects` paths:
```python
from utils.config import get_projects_dir, get_projects_config_dir
```

Use `get_projects_dir()` for project scanning, `get_projects_config_dir()` for members.json paths.

Remove the `PROJECTS_DIR` module-level constant.

### Step B4: Update `gateway/client.py`

Replace:
```python
os.path.expanduser("~/.openclaw/identity/")
```
With:
```python
from utils.config import get_identity_dir
get_identity_dir()
```

Note: `gateway/` importing from `utils/` is allowed — `utils/` has no GTK imports. The rule is `gateway/` must not import from `ui/`. Verified: ARCHITECTURE.md §2 dependency table shows `gateway/` has no restriction against `utils/`.

### Step B5: Update `ui/window.py`

Replace hardcoded `GATEWAY_URL`:
```python
GATEWAY_URL = "ws://localhost:18789"
```
With:
```python
from utils.config import get_gateway_url
```

Use `get_gateway_url()` in `_connect_gateway()`.

### Step B6: Update ARCHITECTURE.md

- Section 2: Add `config.py` under `utils/`
- Section 3: Add §3.x for `utils/config.py` with public API
- Section 10: Document that env vars are now centralized in `utils/config.py`
- Section 12: Add to file inventory

### Step B7: Update Environment Variables doc (Section 10)

Add `XDG_CONFIG_HOME` to the env var table. Note that all config paths are resolved through `utils/config.py`.

### Step B8: Tests

Create `tests/test_config.py`:
- `get_config_dir()` returns `~/.config/crabcakes` by default
- `get_config_dir()` respects `$XDG_CONFIG_HOME`
- `get_config_file()` returns config dir + `config.json`
- `get_projects_config_dir()` returns config dir + `projects`
- `get_projects_dir()` respects `$CRABCAKES_PROJECTS_DIR`
- `get_gateway_url()` respects `$CRABCAKES_GATEWAY_URL`
- `get_identity_dir()` returns `~/.openclaw/identity`

Update existing tests in `test_improve.py` and `test_projects.py` if they mock the old path patterns.

### Verification

- [ ] `python3 -m py_compile utils/config.py`
- [ ] `pytest tests/test_config.py` — all pass
- [ ] `pytest` full suite — no regressions
- [ ] grep for `~/.config/crabcakes` outside of `utils/config.py` — should be zero hits

---

## Fix C: Verify test_architecture.py Test Discovery (#9)

### Problem

QTR noted that `test_architecture.py` uses plain `assert` and `pytest.skip()` without clear `def test_*` naming. He was concerned tests might not be discovered.

### Finding

Already verified: `pytest --collect-only tests/test_architecture.py` collects **3 tests**:
- `test_handlers_do_not_import_each_other`
- `test_models_and_gateway_do_not_import_ui`
- `test_all_documented_public_apis_exist`

**The tests ARE discovered and DO run.** This is a non-issue.

### Action

No code changes needed. Update CODE_AUDIT.md to mark #9 as verified.

---

## Execution Order

1. **Fix A** (streaming dataclass) — self-contained, no cross-module impact
2. **Fix B** (config module) — touches 4 files but mechanical find-and-replace
3. **Fix C** (no-op) — just update audit doc

Total estimated effort: ~45 minutes.

---

## Risk Assessment

| Fix | Risk | Mitigation |
|-----|------|-----------|
| A | Low — dataclass is a drop-in for tuple, existing tests cover behavior | `pytest tests/test_chat_render_handler.py` catches regressions |
| B | Low — path values don't change, just centralized | grep for old paths confirms full migration |
| C | None — no code changes | — |

---

## Post-Implementation

- [ ] Run full `pytest` suite — 0 failures
- [ ] Update ARCHITECTURE.md (Sections 2, 3, 10, 12)
- [ ] Update CODE_AUDIT.md — mark #4, #6, #9 as resolved
- [ ] Commit: `"fix: audit items — streaming dataclass, config module, test verification"`
- [ ] Push to GitHub
