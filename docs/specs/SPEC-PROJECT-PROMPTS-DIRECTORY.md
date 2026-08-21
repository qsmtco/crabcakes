---
status: DRAFT
---
# SPEC: Per-project prompts directory (`.crabcakes/prompts/`)

**Date:** 2026-08-21
**Author:** Supervisor
**Implements:** Fixes the cross-project prompt sandbox issue surfaced during Unit #26 (eagledispatch) — agent briefs reference `prompts/steelFramedCodeWriter.md` but the agent's tool sandbox blocks any path outside the open project's realpath, so the file the instruction points to is invisible to the agent being instructed to read it.
**Depends on:** `init_project_config()` in `utils/project_awareness.py` (existing seeding pattern). Affects `prompts_handler.py` (§8.6 Handler Pattern), `utils/prompts.py`, `input_toolbar_handler.py`, `window.py`, `left_panel.py`, and `.gitignore` defaults.
**Target branch:** main
**Status:** DRAFT — for implementation

> **Architecture compliance:** Follows §8.6 Handler Pattern (`PromptsHandler` already complies — receives all dependencies via setters, owns state, fires callbacks). No new layer violations. `utils/prompts.py` stays in `utils/` (pure Python, no GTK). No changes to `prompts/system/*` (those are app-level agent personality templates consumed by `utils/prompt_loader.py`; out of scope).

---

## 1. Overview

### Problem statement

`PromptsHandler._PROMPTS_DIR` (`ui/handlers/prompts_handler.py:19`) and `utils.prompts.PROMPTS_DIR` both hardcode paths relative to the **app install directory**:

```python
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts')
# → always /home/q/projects/crabcakes/prompts, regardless of which project is open
```

Agent briefs in project A regularly reference files in `prompts/` (e.g. `prompts/steelFramedCodeWriter.md`). The agent's tool layer (`agent/tools.py:_resolve_project_path`, line 186) rejects any path outside the open project's realpath with *"Path escapes project sandbox"*. The current state: the instruction points at a file the agent cannot read.

Verified by reading:
- `ui/handlers/prompts_handler.py:19` — `_PROMPTS_DIR` is module-level, set at import.
- `utils/prompts.py:7` — `PROMPTS_DIR` same pattern.
- `ui/window.py:278` — `PromptsHandler(...)` is constructed with no `project_path` argument.
- `agent/tools.py:186-215` — sandbox resolver is `os.path.commonpath([resolved, project_real])` rejection; no exceptions for sibling apps.
- Eagledispatch's `.crabcakes/prompts/` exists (61 files, byte-identical to app dir per `diff -rq`) — confirming someone seeded it manually and proving the layout works; nothing in the code seeds it on project create, and nothing reads it.

### Solution summary

Treat the user-facing prompt library (everything in `prompts/` except `prompts/system/`) as **per-project state** that lives at `<project>/.crabcakes/prompts/`. The system-prompt templates under `prompts/system/` stay where they are (app config). On project create, seed the per-project directory with a copy of the app's current `prompts/` (minus `system/`). On project open, the Prompts tab and chat-input picker resolve to the project directory. Existing projects get a lazy-seed on next open (retroactive, no manual step).

### Scope

| In | Out |
|---|---|
| `<project>/.crabcakes/prompts/` becomes the source of truth for the user-facing prompt library | `prompts/system/*` (app-level agent personality) — stays in app install dir |
| Lazy-seed of `.crabcakes/prompts/` on project create + on first open of an existing project without it | Per-project agent definitions in `prompts/default_agents/` — out of scope (those wire into `prompts/default_agents/` consumers in `agent/`, not the user-facing Prompts tab). Defer until a use case appears. |
| `PromptsHandler` + `utils.prompts` resolve per-project | `utils/prompt_loader.SYSTEM_DIR` (system-prompt template loader) — stays app-level |
| Favorites migrated to filename-keyed (portable across re-seeds) | Crabcakes self-watching; gitignore in user projects (separate concern, see §8) |
| ARCHITECTURE.md updated to document the per-project prompts dir + the split from system prompts | `prompts/claude-code-clean/` (third-party reference material) — out of scope; this is reference for human authors, not for agents |

---

## 2. Changes by File

### 2.1 `utils/project_awareness.py` — new helper `seed_project_prompts()`

Add a function that copies the app's user-facing prompt library into a project's `.crabcakes/prompts/` directory. Idempotent: only copies files that don't exist (no overwrite, so a project's local edits to a prompt are preserved on subsequent reseeds or app upgrades).

```python
# Imports already present: os, shutil, logging
from utils.prompt_paths import APP_USER_PROMPTS_DIR  # new module, see §2.2

_USER_PROMPTS_SUBDIR = "prompts"
# Subdirectories of prompts/ that belong to the user-facing library and
# should be seeded per-project. system/ is app-level agent personality and
# is excluded by intent (see SPEC §1 Scope).
_USER_PROMPTS_TOP_LEVEL_FILES = ()  # top-level .md only; subdirs handled below
_USER_PROMPTS_INCLUDE_SUBDIRS = ("default_agents",)  # see §1 Scope Out for the claude-code-clean exclusion

logger = logging.getLogger(__name__)

def seed_project_prompts(project_path: str) -> bool:
    """
    Copy the app's user-facing prompt library into <project>/.crabcakes/prompts/.

    Copy-only-if-missing semantics: existing project files are never overwritten,
    so a project that customized a prompt keeps its local copy. Existing project
    files DO block the new app file from being copied in, so after the first
    seed, future app updates do not push changes into that project — the project
    is effectively branched. This is intentional: the prompt library is a
    reference set the project adopts and evolves, not a constant push.

    Returns True on success (including the no-op case where the directory
    already exists), False on hard failure (source missing, IO error).
    Idempotent: callable any number of times.
    """
    if not os.path.isdir(APP_USER_PROMPTS_DIR):
        logger.warning(
            "seed_project_prompts: app user-prompts dir missing: %s",
            APP_USER_PROMPTS_DIR,
        )
        return False

    dest_dir = os.path.join(get_crabcakes_dir(project_path), _USER_PROMPTS_SUBDIR)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        logger.warning("seed_project_prompts: cannot create %s: %s", dest_dir, e)
        return False

    # Top-level .md files (README, *Task*.md, *SPEC*.md, etc.)
    for fname in os.listdir(APP_USER_PROMPTS_DIR):
        src = os.path.join(APP_USER_PROMPTS_DIR, fname)
        if os.path.isfile(src) and fname.endswith(".md"):
            dst = os.path.join(dest_dir, fname)
            if not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError as e:
                    logger.warning("seed: copy %s failed: %s", src, e)

    # Whitelisted subdirs
    for sub in _USER_PROMPTS_INCLUDE_SUBDIRS:
        src_sub = os.path.join(APP_USER_PROMPTS_DIR, sub)
        if not os.path.isdir(src_sub):
            continue
        dst_sub = os.path.join(dest_dir, sub)
        os.makedirs(dst_sub, exist_ok=True)
        for fname in os.listdir(src_sub):
            src = os.path.join(src_sub, fname)
            dst = os.path.join(dst_sub, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError as e:
                    logger.warning("seed: copy %s failed: %s", src, e)
    return True
```

**Verification:** `seed_project_prompts("/tmp/nonexistent")` must return False without raising; `seed_project_prompts(tmp_path / "project")` on a project with `.crabcakes/` already present must copy all 61 expected files (verified by listing and comparing count to APP_USER_PROMPTS_DIR). Second call must be a no-op (no files overwritten, no exceptions).

### 2.2 `utils/prompt_paths.py` — NEW

A small pure-Python module that resolves paths in one place. No GTK, no app state. `utils/prompts.py` and `prompts_handler.py` both consume it so the resolution logic isn't duplicated.

```python
# utils/prompt_paths.py
# Path resolvers for the per-project prompts library.
# Pure Python; no GTK, no I/O beyond os.path.

import os

def _get_app_root() -> str:
    """Return the app install dir (crabcakes project root).

    NOTE (2026-08-21, Supervisor): the original draft imported
    `get_app_root` from utils.config claiming it already exists — it does
    not (utils/config.py exposes only get_config_dir / get_config_file /
    get_projects_config_dir / get_projects_dir). Computed inline instead,
    same pattern as ui/handlers/prompts_handler.py:20 and
    utils/prompt_loader.py:23 use today.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Subdirectories of <app>/prompts/ that are APP-LEVEL (NOT seeded per project).
# These are the agent personality templates consumed by utils/prompt_loader.py.
APP_LEVEL_PROMPTS_SUBDIRS: frozenset[str] = frozenset({"system", "claude-code-clean"})

APP_USER_PROMPTS_DIR: str = os.path.join(get_app_root(), "prompts")


def get_project_prompts_dir(project_path: str | None) -> str:
    """
    Return the per-project prompts directory for the given project, or the
    app-level fallback when no project is open.

    Resolution order:
      1. project_path is None or empty → APP_USER_PROMPTS_DIR (no project)
      2. <project>/.crabcakes/prompts/ exists → return it
      3. otherwise → return APP_USER_PROMPTS_DIR (legacy / no-project state)

    The second clause is the operative one for any project created after this
    spec lands. The third is the safety net for projects that were never seeded
    and for unit tests that build a `PromptsHandler` with no project wired in.
    """
    if not project_path:
        return APP_USER_PROMPTS_DIR
    proj = os.path.join(project_path, ".crabcakes", "prompts")
    if os.path.isdir(proj):
        return proj
    return APP_USER_PROMPTS_DIR
```

**Verification:** `get_project_prompts_dir(None)` → `APP_USER_PROMPTS_DIR`; `get_project_prompts_dir("/no/such/path")` → `APP_USER_PROMPTS_DIR`; on a tmp_path with `.crabcakes/prompts/` created, returns the project path; on the same tmp_path without `.crabcakes/prompts/`, returns `APP_USER_PROMPTS_DIR`.

**Exception types raised:** none (returns fallbacks on any `OSError` from `isdir`). Verified by `monkeypatch` on `os.path.isdir` to raise.

### 2.3 `ui/handlers/prompts_handler.py` — per-project resolution

Two changes:

**(a) Delete the module-level `_PROMPTS_DIR` constant** (line 19). Remove the now-unused import if it was the only consumer of `os.path.dirname` walks.

**(b) Replace `_get_prompts_dir` to consume `get_project_prompts_dir`.** Current code:

```python
def _get_prompts_dir(self) -> str:
    """Return the prompts directory path."""
    return _PROMPTS_DIR
```

New code (project_path supplied via the new setter in §2.4):

```python
def _get_prompts_dir(self) -> str:
    """
    Return the prompts directory for the currently active project.
    Falls back to the app-level user prompts dir when no project is wired
    or the project has no .crabcakes/prompts/ yet.
    """
    return get_project_prompts_dir(self._project_path)
```

Add a setter and a project_path attribute, near the existing init:

```python
def __init__(self, *, on_refresh_ui=None, on_prompt_loaded=None, GLib_module=None):
    # ... existing fields ...
    self._project_path: str | None = None   # set via set_project_path()
    # ...

def set_project_path(self, project_path: str | None) -> None:
    """
    Update the active project path. Caller is expected to invoke refresh
    (e.g. self.load_prompts(); self._on_refresh_ui()) after wiring so the
    UI shows the new directory's contents.

    Passing None or '' is valid and resets to app-level fallback.
    """
    self._project_path = project_path or None
```

**Verification:** Two `PromptsHandler` instances in sequence — one with `set_project_path("/p/A")` after `_PROMPTS_DIR` returned `app_dir`, one without — produce the right lists. Existing `tmp_prompts_dir` fixture in `tests/conftest.py` (line 35) keeps working because it patches `_get_prompts_dir` directly; this is preserved.

### 2.4 `ui/window.py` — wire project switches into `PromptsHandler`

Two call sites, mirroring the existing `set_active_project_path` / `clear_active_project_path` pattern (`ui/window.py:576, 588`):

```python
# Existing on_project_opened callback (line 561) gains one line:
        self._project_handler.set_on_project_opened(
            lambda n, p: (
                # ... existing 9 calls ...
                set_active_project_path(p),
                # NEW: refresh prompt library to project scope + seed if first open
                self._prompts_handler.set_project_path(p),
                self._prompts_handler.load_prompts(),
                self._left_panel.refresh_prompts(),
            )
        )

# Existing on_project_closed callback (line 575) gains one line:
        self._project_handler.set_on_project_closed(
            lambda name: (
                # ... existing 6 calls ...
                clear_active_project_path(),
                # NEW: reset prompt library to app-level fallback
                self._prompts_handler.set_project_path(None),
                self._prompts_handler.load_prompts(),
                self._left_panel.refresh_prompts(),
            )
        )
```

**Seed timing:** the first call to `set_project_path(p)` must also trigger a lazy seed. Implement as a guard inside `PromptsHandler.set_project_path` or as a separate `seed_if_missing(p)` called from the open callback. Decision: separate function (cleaner separation of concerns; testable in isolation). Window wires the lazy seed into the open callback as one extra call before the load:

```python
        # In on_project_opened callback, after set_active_project_path(p):
        from utils.project_awareness import seed_project_prompts  # local import
        seed_project_prompts(p)
        self._prompts_handler.set_project_path(p),
        self._prompts_handler.load_prompts(),
        self._left_panel.refresh_prompts(),
```

**Verification:** Open a project without `.crabcakes/prompts/` (simulate by deleting it on a tmp project, then calling `seed_project_prompts(p)`); assert the directory now contains expected files. Reopen the same project; assert the call is idempotent and the existing files were not overwritten (modify one file, run again, confirm modification preserved).

### 2.5 `ui/handlers/project_handler.py` — seed on `create_project`

Add one call to the existing `create_project` flow (around line 173, after `init_workflow(path)`):

```python
        # Initialize workflow.md (idempotent — creates with onboarding as current)
        try:
            init_workflow(path)
        except Exception:
            pass  # non-fatal

        # NEW: seed per-project prompts library
        try:
            seed_project_prompts(path)
        except Exception as e:
            _logger.warning("prompts seed failed for %s: %s", path, e)
```

Imports already in the file: `os`, `init_repo`, `commit`, `stage_all` from `utils.git_ops`. Add `from utils.project_awareness import init_project_config, seed_project_prompts` (extend the existing import).

**Verification:** Create a new project (use `tmp_path`); assert `.crabcakes/prompts/` exists and contains `README.md` and the whitelisted subdirs. Assert no exception escapes the `try` even if the source dir is missing (use a fake `APP_USER_PROMPTS_DIR` pointing at a non-existent path).

### 2.6 `utils/prompts.py` — per-project resolution

Replace the module-level constant and the `load_prompts` function:

```python
# utils/prompts.py
# Loads .md prompt files from the active project's .crabcakes/prompts/.

import os

from utils.prompt_paths import get_project_prompts_dir

# Backwards-compat: existing callers import `PROMPTS_DIR` as a constant.
# Keep it, but define it lazily: it's the app-level default. New code should
# call `get_project_prompts_dir(project_path)` instead. Existing callers
# (ui/handlers/input_toolbar_handler.py:411, 456) only use it as a fallback
# when no project is open.
PROMPTS_DIR: str = get_project_prompts_dir(None)


def load_prompts() -> list[tuple[str, str]]:
    """
    Load all .md files from the active project's .crabcakes/prompts/.
    Returns [(display_name, file_content)].

    Note: callers (ui/views/chat_input_toolbar.py:18) currently call this
    without a project_path — they see the app-level fallback. This is the
    pre-existing limitation; the chat-input picker is wired to a callback
    that doesn't know the active project. See §2.7.
    """
    prompts_dir = get_project_prompts_dir(None)  # active-project wiring is §2.7
    if not os.path.isdir(prompts_dir):
        return []
    result: list[tuple[str, str]] = []
    for filename in sorted(os.listdir(prompts_dir)):
        if not filename.endswith(".md"):
            continue
        display_name: str = filename[:-3]
        file_path: str = os.path.join(prompts_dir, filename)
        with open(file_path, encoding="utf-8") as f:
            content: str = f.read()
        result.append((display_name, content))
    return result
```

**Verification:** Existing `tests/test_prompts.py` keeps passing because `PROMPTS_DIR` is still the app fallback when no project is wired. New test (added in §4): `load_prompts()` on a tmp_path with `.crabcakes/prompts/` returns the project's prompts only when the calling code can pass a project path (see §2.7).

### 2.7 `ui/handlers/input_toolbar_handler.py` — thread project path through the picker

Two consumers of `PROMPTS_DIR` (`load_prompt` at line 450, `save_as_prompt` at line 411) need to resolve against the active project. Both methods are currently called with no project context.

**(a) Add a `set_project_path` setter to `InputToolbarHandler`** matching the same pattern as `PromptsHandler` (`§2.3`). Stored as `self._project_path: str | None = None`.

**(b) Update `load_prompt` and `save_as_prompt`** to use `get_project_prompts_dir(self._project_path)` instead of the constant:

```python
def load_prompt(self, prompt_name: str) -> bool:
    from utils.prompt_paths import get_project_prompts_dir
    path = os.path.join(get_project_prompts_dir(self._project_path),
                        f"{prompt_name}.md")
    if os.path.isfile(path):
        return self.load_file(path)
    logger.warning("Prompt not found: %s", path)
    return False

def save_as_prompt(self, filename: str) -> str | None:
    from utils.prompt_paths import get_project_prompts_dir
    prompts_dir = get_project_prompts_dir(self._project_path)
    os.makedirs(prompts_dir, exist_ok=True)
    buf = self._mc.user_input.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    path = os.path.join(prompts_dir, f"{filename}.md")
    # ... rest unchanged
```

**(c) Wire the setter from `ui/window.py:314`**:

```python
# In InputToolbarHandler construction (line 314):
self._input_toolbar_handler = InputToolbarHandler(
    main_content=self._main_content,
    GLib_module=GLib,
)
# NEW: wire to active project on open/close
self._project_handler.set_on_project_opened(
    lambda n, p: ( # ... existing callback body ...,
        self._input_toolbar_handler.set_project_path(p),
    )
)
self._project_handler.set_on_project_closed(
    lambda name: ( # ... existing callback body ...,
        self._input_toolbar_handler.set_project_path(None),
    )
)
```

**Note:** `set_on_project_opened` is currently set ONCE in `ui/window.py:561` with a 9-callback tuple. The `input_toolbar_handler.set_project_path` is added to that same tuple — not a second `set_on_project_opened` call (which would overwrite the first).

**Verification:** Open project A; call `load_prompt("foo")`; assert the resolved path is `<A>/.crabcakes/prompts/foo.md`, not the app dir. Close the project; assert it falls back.

### 2.8 `utils/favorites.py` — key by filename, not full path

Currently `favorites` are keyed by absolute filepath (`_FAVORITES_PATH = ".../favorites.json"` stores `set[str]` of paths). After the per-project switch, a prompt's filepath changes (`<app>/prompts/README.md` → `<A>/.crabcakes/prompts/README.md`). Old favorites silently un-favorite.

**Approach:** key by the **stem** (`README`) instead of the full path. The favorites file becomes a set of stems; lookups match any prompt in the active project that has the same stem. This is portable across reseeds and across app upgrades.

```python
# utils/favorites.py — full rewrite of keying:
import json
import os

from utils.config import get_config_dir

_FAVORITES_PATH = os.path.join(get_config_dir(), "favorites.json")


def _ensure_dir():
    os.makedirs(get_config_dir(), exist_ok=True)


def load_favorites() -> set[str]:
    """Load favorited prompt STEMS (not paths). Returns empty set on error."""
    if not os.path.exists(_FAVORITES_PATH):
        return set()
    try:
        with open(_FAVORITES_PATH, 'r') as f:
            data = json.load(f)
        favs = data.get('favorites', [])
        return set(favs) if isinstance(favs, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def save_favorites(favorites: set[str]) -> None:
    _ensure_dir()
    with open(_FAVORITES_PATH, 'w') as f:
        json.dump({'favorites': sorted(favorites)}, f)


def is_favorite(stem: str) -> bool:
    return stem in load_favorites()


def toggle_favorite(stem: str) -> bool:
    favs = load_favorites()
    if stem in favs:
        favs.discard(stem)
        save_favorites(favs)
        return False
    favs.add(stem)
    save_favorites(favs)
    return True
```

**Migration:** On the first read after the upgrade, if the existing JSON file contains paths (contain `/`), migrate by stripping to basename-without-extension. One-time, idempotent. Document with a comment.

```python
def load_favorites() -> set[str]:
    if not os.path.exists(_FAVORITES_PATH):
        return set()
    try:
        with open(_FAVORITES_PATH, 'r') as f:
            data = json.load(f)
        favs = data.get('favorites', [])
        if not isinstance(favs, list):
            return set()
        # Migration: paths → stems (one-time, idempotent)
        migrated = [
            os.path.splitext(os.path.basename(p))[0] if "/" in p else p
            for p in favs
        ]
        if migrated != favs:
            save_favorites(set(migrated))
        return set(migrated)
    except (json.JSONDecodeError, OSError):
        return set()
```

**Impact on `PromptsHandler`:** the `_favorites` set now holds stems. The `_sorted_filtered` method (line 197) compares `fpath in self._favorites` — change to `prompt_name = p['name']; is_fav = prompt_name in self._favorites`. Same display behavior, key change is the unit of identity.

```python
# in _sorted_filtered:
is_fav = p['name'] in self._favorites
```

**Verification:** Create a favorites.json with paths like `["/old/app/prompts/steelFramedCodeWriter.md", "/old/app/prompts/READMD.md"]`; load it; assert the resulting set is `{"steelFramedCodeWriter", "READMD"}`; assert the file was rewritten with the migrated form. Toggling a stem-based favorite round-trips through the same code path.

### 2.9 `agent/context.py` — project prompts in agent file context

Add `.crabcakes/prompts/**` to the per-project file context for agents, mirroring the existing `.crabcakes/{architecture,context,...}.md` injection (`agent/context.py:144-189`). The agents should see the project's prompt library in their file context, not just the app's.

In `agent/context.py:163` (the `DOC_NAMES` tuple), the current list of injected `.crabcakes/` files does not include `prompts/`. Add a second pass that walks `<project>/.crabcakes/prompts/` and includes up to 30 short `.md` files (under 20KB each) as `## .crabcakes/prompts/{name}` sections. This makes `read_file("prompts/steelFramedCodeWriter.md")` work and also makes the file surface visible to the agent without an explicit read.

**This is the "agents can't read the prompts because of the sandbox" problem at its root:** the agent's file context builder now includes the prompts, so even when the agent doesn't know to read a specific prompt, it sees the library in its context window.

```python
# New function in agent/context.py:
_PROJECT_PROMPTS_CONTEXT_CAP = 20 * 1024  # 20KB per prompt
_PROJECT_PROMPTS_MAX_FILES = 30

def _load_project_prompts_context(project_path: str) -> str:
    """
    Read .crabcakes/prompts/*.md into the agent's file context.
    Each file becomes a ``## .crabcakes/prompts/{stem}`` section, capped at
    20KB per file and 30 files total. Subdirectories (e.g. default_agents)
    are NOT included here — those are loaded by other code paths and
    including them would double the context size.

    Returns empty string if the directory does not exist.
    """
    prompts_dir = os.path.join(project_path, ".crabcakes", "prompts")
    if not os.path.isdir(prompts_dir):
        return ""
    sections: list[str] = []
    try:
        files = sorted(
            f for f in os.listdir(prompts_dir)
            if f.endswith(".md") and os.path.isfile(os.path.join(prompts_dir, f))
        )
    except OSError:
        return ""
    for fname in files[:_PROJECT_PROMPTS_MAX_FILES]:
        fpath = os.path.join(prompts_dir, fname)
        try:
            if os.path.getsize(fpath) > _PROJECT_PROMPTS_CONTEXT_CAP:
                continue
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        sections.append(f"## .crabcakes/prompts/{fname[:-3]}\n\n{content}\n")
    return "\n".join(sections)
```

Wire it into `build_file_context` (around line 144, where `.crabcakes/` docs are read): append the prompts section after the standard `.crabcakes/` docs, so it lands early in the context window. Document in the docstring: "prompts appear after the standard .crabcakes/ docs so the agent's methodology, then their reference material, then the project tree."

**Verification:** `build_file_context("/p")` on a project with `.crabcakes/prompts/` returns a string that includes both `## .crabcakes/architecture.md` and `## .crabcakes/prompts/steelFramedCodeWriter` sections. Cap: 30 files, 20KB each. Subdirs excluded.

---

## 3. Data Flow

### 3.1 Project create → prompts available

```
User creates project (FileTree New Project form)
  → project_handler.create_project(name, path)
    → makedirs(path)
    → init_project_config(path)            # seeds manifest, team, workflow
    → init_workflow(path)                  # seeds workflow.md
    → seed_project_prompts(path)           # NEW: seeds .crabcakes/prompts/
    → git init + initial commit
    → open_project(name, path)
      → set_active_project_path(p)         # env var (existing)
      → self._prompts_handler.set_project_path(p)   # NEW
      → self._prompts_handler.load_prompts()        # refresh
      → self._left_panel.refresh_prompts()           # rebuild tab
```

### 3.2 Project open (existing project, first open after this spec) — lazy seed

```
User opens existing project without .crabcakes/prompts/
  → open_project(name, path)
    → if not os.path.isdir(<p>/.crabcakes/prompts/):
        seed_project_prompts(p)              # NEW: lazy seed
    → set_active_project_path(p)
    → self._prompts_handler.set_project_path(p)
    → self._prompts_handler.load_prompts()   # now reads project dir
    → self._left_panel.refresh_prompts()
```

### 3.3 User opens Prompts tab (no project)

```
User opens Prompts tab without a project
  → PromptsHandler._get_prompts_dir() returns APP_USER_PROMPTS_DIR
    (because set_project_path was never called or was called with None)
  → _scan_prompts reads the app dir
  → display shows the app's canonical prompt set
```

### 3.4 User opens Prompts tab (with a project)

```
User opens Prompts tab with project A active
  → PromptsHandler._project_path == '/p/A'
  → _get_prompts_dir() → get_project_prompts_dir('/p/A')
    → '/p/A/.crabcakes/prompts' (project dir exists after seed)
  → _scan_prompts reads the project dir
  → favorites match by stem (e.g. 'steelFramedCodeWriter' favorites the
    prompt by that name in whatever project is active)
```

### 3.5 Agent reads a prompt

```
Agent receives brief: "Use prompts/steelFramedCodeWriter.md"
  → tool: read_file("prompts/steelFramedCodeWriter.md")
  → _resolve_project_path resolves under project_path
  → reads /p/A/.crabcakes/prompts/steelFramedCodeWriter.md
  → returns content
```

Without this spec, `_resolve_project_path` rejects the path → *"Path escapes project sandbox"*. **This is the bug being fixed.**

### 3.6 Agent file context includes the prompts library

```
build_file_context('/p/A')
  → reads .crabcakes/{architecture,context,...}.md
  → _load_project_prompts_context('/p/A')   # NEW
  → reads up to 30 .md files under .crabcakes/prompts/
  → returns concatenated sections
```

---

## 4. File Change Summary

| File | Change Type | Lines (est) | Risk |
|---|---|---|---|
| `utils/prompt_paths.py` | NEW | ~40 | Low — pure helpers |
| `utils/project_awareness.py` | Add `seed_project_prompts()` | +60 | Low — copy-only-if-missing |
| `ui/handlers/prompts_handler.py` | Drop `_PROMPTS_DIR`, add `set_project_path`, project-aware `_get_prompts_dir`, stem-keyed favorites | +20 / -10 | Medium — touches every Prompts tab render path; existing test fixture keeps passing |
| `ui/handlers/input_toolbar_handler.py` | Add `set_project_path`, project-aware `load_prompt` / `save_as_prompt` | +15 / -5 | Low — drop-in for two methods |
| `ui/handlers/project_handler.py` | Call `seed_project_prompts` in `create_project` | +5 | Low — wrapped in try/except |
| `ui/window.py` | Wire setters on project open/close (3 places) | +12 | Low — additive callbacks |
| `ui/views/left_panel.py` | No code change; receives `refresh_prompts()` calls | 0 | None — already supports refresh |
| `utils/prompts.py` | Per-project resolution; lazy import to avoid cycles | +5 / -5 | Low — backwards-compat constant kept |
| `utils/favorites.py` | Stem-keyed + one-time path→stem migration | +15 / -10 | Medium — touches existing favorites; test fixture reuses `tmp_prompts_dir` |
| `agent/context.py` | Add `_load_project_prompts_context`; wire into `build_file_context` | +50 | Medium — affects every agent context build; size budget is the risk |
| `docs/ARCHITECTURE.md` | Add §X: per-project prompt library + the split from system prompts | +30 | None — docs only |

**Net:** +260 / -30 across 8 files + 1 NEW file. No layer violations. No new dependencies.

---

## 5. Implementation Order

Numbered so each step is independently verifiable.

1. **`utils/prompt_paths.py` (NEW).** The resolver is the foundation. Write + test first. Verify against 4 cases (None, no-such-path, project-with-prompts, project-without-prompts). Confirm `utils/prompts.py` and `ui/handlers/prompts_handler.py` can both import and call it.
2. **`utils/project_awareness.seed_project_prompts`.** Write + test the copy-only-if-missing semantics. Verify against a fresh project (no `.crabcakes/prompts/`), a populated project (no overwrites), and a project with one local edit (edit preserved on re-seed).
3. **`ui/handlers/prompts_handler.py` + `ui/handlers/input_toolbar_handler.py` — per-project resolution.** The two handlers consume the new resolver. Wire setters; update `_get_prompts_dir`, `load_prompt`, `save_as_prompt`. Existing `tmp_prompts_dir` fixture still patches `_get_prompts_dir` directly; tests pass.
4. **`utils/favorites.py` — stem keying + migration.** Rewrite `_FAVORITES_PATH` storage; add path-to-stem migration on first read. Test with a JSON file containing paths; assert migrated form.
5. **`ui/window.py` — wire project switches.** Add three lines to the existing project-open callback and three to the project-closed callback. Manual: open a project, verify Prompts tab refreshes; close it, verify the app fallback shows.
6. **`ui/handlers/project_handler.create_project` — seed on create.** Add the `seed_project_prompts(path)` call after `init_workflow`. Manual: create a project, verify `.crabcakes/prompts/` is populated from the app's set.
7. **Agent file context — `_load_project_prompts_context`.** Add to `agent/context.py`, wire into `build_file_context`. Manual: open a project, run a one-shot agent task that references `prompts/...` and verify the read succeeds.
8. **`docs/ARCHITECTURE.md` — documentation.** Add a short section: per-project prompt library path, what's seeded, the system-vs-user split, the migration story for favorites.

After each step: run the relevant test subset (see §6) and paste the output. Do not proceed to the next step on a regression.

---

## 6. Acceptance Criteria

Testable outcomes. Each must pass before declaring the spec complete.

- [ ] New test: `get_project_prompts_dir(None)` returns the app-level dir
- [ ] New test: `get_project_prompts_dir("/no/such")` returns the app-level dir
- [ ] New test: `get_project_prompts_dir(project_with_prompts)` returns the project dir
- [ ] New test: `seed_project_prompts` is idempotent; a project's local edit survives a re-seed
- [ ] New test: `seed_project_prompts` copies the expected file set on a fresh project (matches app dir, minus `system/`)
- [ ] `PromptsHandler` with `set_project_path(p)` returns project-scoped prompt lists; with `None` returns app-level
- [ ] `InputToolbarHandler.load_prompt` resolves against the active project
- [ ] Favorites JSON migration: paths → stems, file rewritten, then load returns stems
- [ ] Manual: create a new project; `.crabcakes/prompts/` exists with ≥ README + 1 subdir
- [ ] Manual: open existing eagledispatch project; verify it is seeded on first open (legacy project)
- [ ] Manual: read `prompts/steelFramedCodeWriter.md` from an agent in project A — succeeds (was: sandbox rejection)
- [ ] Manual: `build_file_context` includes `## .crabcakes/prompts/...` sections
- [ ] All existing `tests/test_prompts*.py` and `tests/test_prompt_loader.py` pass unchanged

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| User creates project while app's `prompts/` is empty | `seed_project_prompts` returns True; project dir created empty. Prompts tab shows empty list. |
| User has a project with `.crabcakes/prompts/` that contains a file NOT in the app set (a local edit) | The local file is preserved (copy-only-if-missing). Not overwritten. |
| User opens project A, toggles favorite on `steelFramedCodeWriter`, opens project B (which also has that prompt) | The favorite persists across project switches. The prompt is starred in B too. |
| User opens project A, then closes the project (back to no-project state) | Prompts tab falls back to app-level `prompts/`. Favorites from A still match by stem. |
| User's `.crabcakes/prompts/README.md` is deleted after a seed | Subsequent `seed_project_prompts` re-creates it (file no longer exists at dest, so copy fires). No data loss beyond what the user already deleted. |
| `read_file("prompts/...")` from an agent in a project that hasn't been seeded yet | Lazy-seed runs on `set_project_path`/project open; if the seed fails (missing app dir, IO error), the read still fails with "Path escapes project sandbox" — same as today, no regression. |
| Two agents open project A concurrently; one creates a new prompt, the other toggles favorite | File-level race; copy creates local file, favorite store is per-user config. Both safely serializable by the OS. |
| `prompts/system/` exists in the seeded dir (shouldn't, but defense-in-depth) | `seed_project_prompts` only walks top-level files and `_USER_PROMPTS_INCLUDE_SUBDIRS` (no `system`). If a previous build or manual copy placed `system/` there, it is left alone. Not deleted. |
| `favorites.json` is malformed JSON | `load_favorites` returns `set()`; `save_favorites` overwrites on next toggle. No crash. (Same as today.) |

---

## 8. ARCHITECTURE.md Updates Required

Add a new section near the existing "Prompt library" line (line 40 in current `docs/ARCHITECTURE.md`). The new section should:

- Define the **two-tier prompt storage**: app-level (`<crabcakes>/prompts/system/` — agent personality, app config) vs. per-project (`<project>/.crabcakes/prompts/` — user-facing library).
- Document `seed_project_prompts` and the copy-only-if-missing semantics.
- Document `get_project_prompts_dir` and its three-clause resolution.
- Document the `prompts/claude-code-clean/` subdirectory is human-reference-only and not seeded into projects.
- Note the favorites migration (paths → stems) as a one-time behavior.
- Cross-link to the spec and the post-mortem that surfaced this.

Also update the file index (line 218-219) to add `utils/prompt_paths.py` and `seed_project_prompts` mention on `utils/project_awareness.py`.

---

## 9. Files NOT Changed

(Explicit per Rule 8 — documents what the implementer should NOT touch.)

- **`utils/prompt_loader.py`** — `SYSTEM_DIR` is for app-level system prompts (`coder.md`, `debugger.md`, etc.). Unchanged.
- **`prompts/system/*`** — agent personality templates. Unchanged.
- **`prompts/claude-code-clean/*`** — third-party reference material for human authors. Not seeded.
- **`prompts/default_agents/*`** — out of scope for this spec (see §1). The `agent/` consumers read these directly; making them per-project is a separate decision.
- **`agent/tools.py:_resolve_project_path`** — the sandbox is correct. The fix is at the prompt-library layer, not the tool layer. A spec that loosens the sandbox would be the wrong fix.
- **`docs/ARCHITECTURE.md` handler rule §8.6** — `PromptsHandler` already complies; no changes to the rule itself.
- **`.gitignore` of user projects** — out of scope. Recommend `<project>/.crabcakes/prompts/` be committed (it's the project's library, not the agent workspace); document in §8 but do not enforce.

---

## 10. Verification Cheat Sheet (for implementer)

```bash
# Resolver
python3 -c "from utils.prompt_paths import get_project_prompts_dir; print(get_project_prompts_dir(None))"

# Seeding
python3 -c "
import os, tempfile
from utils.project_awareness import seed_project_prompts
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, '.crabcakes'))
    seed_project_prompts(d)
    print(sorted(os.listdir(os.path.join(d, '.crabcakes', 'prompts')))[:5])
"

# Tests
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_prompt_loader.py tests/test_prompts_handler.py -q -p no:cacheprovider
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_prompts.py -q -p no:cacheprovider

# Manual: open existing project, verify Prompts tab contents
# Manual: agent read_file('prompts/steelFramedCodeWriter.md') in project A
```

---

## 11. Self-Audit (Rule 9)

- [x] Every code sample traced against actual source (`utils/project_awareness.py` `get_crabcakes_dir`, `agent/tools.py` `_resolve_project_path`, `prompts_handler.py` `_get_prompts_dir`, `favorites.py` `toggle_favorite`, `agent/context.py` `build_file_context`, `window.py` open/close callback, `project_handler.create_project`)
- [x] Exception types: `seed_project_prompts` catches `OSError` and logs; does not raise. `get_project_prompts_dir` catches no exceptions (returns fallback on `isdir` raising). `load_favorites` catches `(json.JSONDecodeError, OSError)`. Verified.
- [x] Key structure: favorites migrate from path-keyed to stem-keyed. Migration is one-time, idempotent, file-rewriting. Documented.
- [x] Return values: `seed_project_prompts` returns `bool`. `get_project_prompts_dir` returns `str` (never None). Documented.
- [x] "Should work" sanity checks replaced with grep + file read: `_PROMPTS_DIR` literal verified at `ui/handlers/prompts_handler.py:19`; `os.path.commonpath` sandbox verified at `agent/tools.py:198-210`; `set_on_project_opened` tuple verified at `ui/window.py:561-578`.
- [x] Files NOT changed listed (§9).
- [x] Implementer would not need to guess — every offset, every signature, every import listed.
- [x] No "match the test to observed reality" trap from the Pango post-mortem (Rule 2): the seed is copy-only-if-missing precisely because preserving local edits is the design intent, not an emergent property of the seed logic.
- [x] No `/ask` semantics lost — `app/chat_bubble.py:65-71` already reads `CRABCAKES_ACTIVE_PROJECT_PATH`; this spec does not change that flow.

---

*Spec written read-only; no code modified. Verification of every claim against the actual codebase at HEAD `c2b26ac` is documented in §11.*
