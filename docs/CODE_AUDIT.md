# crabCakes Code Audit
**Auditor:** QTR (Kage-7)
**Date:** 2026-04-12
**Files Reviewed:** 22 source files across models/, gateway/, ui/, utils/, tests/

---

## Architecture — 8/10

### What's Solid

The layered structure is correct and enforced by automated tests:

| Layer | Files | Rule |
|---|---|---|
| `models/` | agents.py, colors.py | Pure data. No UI. |
| `gateway/` | client.py | WebSocket only. No UI. |
| `utils/` | projects, escaping, markdown, block_parser, etc. | Pure logic. No GTK imports. |
| `ui/handlers/` | chat_handler, gateway_handler, media_handler, etc. | UI logic isolated from widgets. |
| `ui/views/` | left_panel, main_content, chat_bubble, etc. | Widgets only. |

**Handler pattern applied consistently.** Each handler owns one domain and doesn't reach into others. Thread safety via `GLib.idle_add` is uniform across all async entry points. No handler imports another handler — enforced by AST tests in `test_architecture.py`.

**Pipeline design is clean:**
```
raw text → extract_blocks() → per-segment widget → bubble
```
Each step is a separate, testable function. Block parsing, markdown conversion, and Pango escaping are independently testable units.

**Security manifests** in each file (what it reads, writes, network calls) are excellent practice. Explicit contracts about what each module can do.

**Color system** is simple and intentional — `next_agent_color()` / `next_project_color()` with separate round-robin counters.

---

## Critical Issues

### 1. window.py is a composition god-object

`MainWindow._build()` is ~150 lines of widget assembly and cross-handler wiring. It:
- Creates every handler and view
- Injects `GLib` everywhere
- Sets up all cross-handler callbacks (12+ callback wires)
- Manages the shared `agent_to_project` dict

There's no formal composition root pattern. The file grew organically. If a new handler needs dependencies, window.py gets another injection. This is the most common GTK app failure mode — all composition logic accumulates until it's unmaintainable.

**Risk:** Adding many more handlers or features will make window.py the bottleneck. A formal assembler or composition class would be more maintainable.

### 2. Shared mutable state with no contract

`_agent_to_project` (a dict) is passed by reference to both `ChatHandler` and `ProjectHandler`:
- `ProjectHandler` writes it (`toggle_agent`, `open_project`)
- `ChatHandler` reads it (`on_chat_event`)

There's no interface, no lock, no observable. It works because GTK is single-threaded, but the architecture relies on an implicit convention rather than an explicit contract.

**Risk:** If someone accidentally modifies `_agent_to_project` from the wrong handler, there's no safeguard.

### 3. Silent failures everywhere

- `load_members()` returns `[]` on error
- `get_chat_box()` returns `None` if no tab found
- `send_message()` silently does nothing if not connected
- `get_prompt_content()` returns `(name, '')` on OSError

No exceptions, no logging, no signal to the caller that something went wrong.

**Risk:** Debugging is hard. When something fails, you get empty behavior rather than a clear error. Makes regression difficult to catch.

---

## Moderate Issues

### 4. Config loading is duplicated and ad-hoc — RESOLVED

~~Three different config-loading patterns in three different places:~~
~~- `utils/improve.py` — reads `~/.config/crabcakes/config.json` directly~~
~~- `gateway/client.py` — reads `~/.openclaw/identity/` directly~~
~~- `utils/projects.py` — reads from `~/.config/crabcakes/projects/` directly~~

Centralized in `utils/config.py` (2026-04-13). All paths now go through typed helpers
(`get_config_dir()`, `get_config_file()`, `get_projects_dir()`, `get_projects_config_dir()`,
`get_gateway_url()`, `get_identity_dir()`). Env vars `$XDG_CONFIG_HOME`, `$CRABCAKES_PROJECTS_DIR`,
and `$CRABCAKES_GATEWAY_URL` are respected. Zero hardcoded `os.path.expanduser` paths remain
outside `utils/config.py`.

### 5. PromptsHandler has fragile path resolution

```python
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts')
```

Four levels of `os.path.dirname` to resolve a sibling `prompts/` directory. Works but hard to audit. If the file moves, the path breaks silently.

**Risk:** Refactoring by moving files breaks this silently.

### 6. `_streaming_bubbles` uses positional tuple access — RESOLVED

~~Five-element tuple, positional access. Adding a sixth field requires updating every access site.~~

Replaced with `StreamingBubble` dataclass in `models/streaming.py` (2026-04-13). All tuple
unpack sites in `chat_render_handler.py` updated to use named attributes (`sb.container`,
`sb.label`, `sb.role`, `sb.plain_text`, `sb.bubble`). Adding a new field now requires only
adding one dataclass attribute.

### 7. "thinking" events handled differently from other special events

`thinking` events fall back to `build_role_bubble()` rather than getting a proper card renderer like `file_read` and `tool_call`. Inconsistent with the rest of Phase 4.

**Risk:** Low. Works but is technically inconsistent.

---

## Minor Issues

### 8. `ChatRenderHandler` and `ChatHandler` have different reentrancy keys

- Reentrancy guard uses `session_key` directly
- Message grouping uses `f"{role}:{session_key}"`

Slightly different keys for similar concepts. Not wrong, but adds cognitive overhead.

### 9. Test file may not run correctly — VERIFIED NON-ISSUE

~~`test_architecture.py` uses plain `assert` statements and `pytest.skip()` without `@pytest.fixture` or `def test_*` naming.~~

Verified 2026-04-13: `pytest --collect-only tests/test_architecture.py` collects 3 tests.
The test functions are named `test_handlers_do_not_import_each_other`, `test_models_and_gateway_do_not_import_ui`,
and `test_all_documented_public_apis_exist` — all pass. No code changes needed.

---

## What's Genuinely Good

1. **Pipeline architecture** — clean separation of text processing stages
2. **AST-enforced architecture rules** — real automated enforcement, not just comments
3. **Security manifests** — each file documents its I/O surface explicitly
4. **Thread safety discipline** — uniform `GLib.idle_add` pattern across all handlers
5. **Color system** — simple, round-robin, intentional
6. **Test structure** — tests are organized by module, with conftest.py for shared fixtures

---

## Summary

crabCakes is well-structured and shows genuine architectural discipline. The handler pattern is applied correctly, layer isolation is enforced, and the code is readable.

**Main risks:**
- window.py as composition bottleneck as the app grows
- Silent failure modes making debugging difficult
- Duplicated config loading across utilities

**Priority fixes:**
1. Extract a composition/assembler class from window.py
2. Add logging or raise exceptions on silent failure paths
3. Create a shared `Config` module

---

*QTR — Kage-7 — The blade that cuts time. 🎯*