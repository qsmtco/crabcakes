# Proposal: Replace GTK4 UI with a Local Web UI (FastAPI + Browser SPA)

**Date:** 2026-07-15
**Author:** QTR
**Status:** ⚠️ PROPOSAL — Not implemented. Awaiting Captain approval.
**Motivation:** Ongoing Pango markup failures (recent incident 2026-07-15 10:56 PDT — `Failed to set text '...&quot;...&#x27;...'` rendering raw agent output to terminal), accumulating edge cases in `utils/escaping.py` and `utils/markdown.py`, and the long-term cost of maintaining a 24K-line PyGObject codebase.
**Related:** `docs/proposals/PROPOSAL-fix-malformed-pango-markup.md` (already-shipped partial fix for the same bug class — evidence the Pango escape layer is a recurring source of regressions).

---

## 1. Executive Summary

Replace the GTK4 desktop shell (`ui/`, `main.py`) with a local FastAPI server that serves a single-page browser app. The agent runtime, gateway client, conversation persistence, and all business logic remain **completely unchanged** in Python — only the rendering layer changes. The browser becomes the UI surface, served from `http://127.0.0.1:8765/`.

This proposal does **not** change:
- `agent/` — runtime, tools, streaming, conversation management
- `gateway/` — WebSocket client, protocol handling
- `models/` — domain types
- `utils/` — escaping, markdown, escaping logic
- `prompts/` — agent system prompts
- `knowledge/` — RAG corpus
- Conversation persistence on disk
- OpenClaw gateway contract

This proposal **only** changes:
- `main.py` — from `Gtk.Application.run()` to `uvicorn.run()`
- `ui/` — replaced by `webui/` (FastAPI app + static SPA bundle)
- `pyproject.toml` — replaces `PyGObject` with `fastapi` + `uvicorn`

**Net code change:** ~24,000 lines of `ui/` replaced with ~3,000-5,000 lines of `webui/`. **Net LoC reduction:** ~70%. **Net bug surface reduction:** Pango escape layer (currently 30+ regex passes, multiple known bug families) becomes a 5-line `textContent` assignment.

---

## 2. Problem Statement

The current rendering layer has three classes of recurring problems that motivate this proposal.

### 2.1 Pango Markup Fragility (the immediate trigger)

GTK4 widgets require Pango-flavored XML markup via `Gtk.Label.set_markup()`. Pango is **strict** about tag balance and entity encoding. The runtime maintains:

- `utils/escaping.py` (300+ lines) — tag whitelisting, entity decoding, stack-based tag balancer
- `utils/markdown.py` — Markdown→Pango converter with ZWSP hack for adjacent bold blocks
- `utils/markdown.py` — auto-link detection with HIGH-6 scheme allowlist
- `ui/styles.py` — CSS with documented GTK-incompatible properties removed
- `ui/gtk_safe_link.py` — `make_safe_label()` wrapper to gate link activation on scheme allowlist

**Evidence of fragility:**
- The incident on 2026-07-15 10:56 PDT produced: `Failed to set text '...&quot;...&#x27;...' — Element 'b' was closed, but the currently open element is 'i'`. This is the **exact bug class** that `PROPOSAL-fix-malformed-pango-markup.md` (shipped) was supposed to fix. The fix is incomplete.
- Five subsequent `Phase X` commits to `utils/escaping.py` and `utils/markdown.py` between 2026-05-10 and 2026-06-12 indicate ongoing maintenance churn.
- LLM output frequently contains raw HTML entities (`&quot;`, `&#x27;`, `&lt;`) that escape detection is imperfect.
- Streaming path (`ui/handlers/chat_render_handler.py:434-475`) re-runs `escape_for_pango` + `format_markdown` + `set_markup` on every throttled delta — performance + correctness landmines.

### 2.2 Testing Friction

The UI layer has minimal test coverage because GTK widgets require a display server. Existing tests mock GTK extensively (`tests/test_chat_render_handler.py`, `tests/test_main_content.py`). The actual visual layer (CSS, layout, accessibility) is untested.

### 2.3 Distribution Friction

PyGObject has hard system dependencies (`libgtk-4-1`, `libgirepository-1.0-1`, `libpango-1.0-0`, `libcairo2`, GObject Introspection typelibs). Installation on fresh machines requires `apt install` or `brew install` of 10+ system packages. Distribution via PyPI is impossible. Containerization requires a full GTK runtime image (~400MB).

---

## 3. Goals & Non-Goals

### 3.1 Goals

1. **Eliminate Pango markup failures.** Browser DOM (`textContent` / `innerHTML`) is forgiving and well-understood. No tag balancer needed.
2. **Reduce UI code surface by ≥60%.** Replace ~24K lines of PyGObject widget code with ~3-5K lines of HTML+CSS+vanilla JS or a small SPA.
3. **Preserve 100% of business logic.** Zero changes to `agent/`, `gateway/`, `models/`, `utils/` (except escaping/markdown which become dead code).
4. **Maintain desktop UX.** Run as a system tray icon + browser tab on `127.0.0.1`. No external network exposure. No remote access unless explicitly enabled.
5. **Enable modern UI affordances.** Keyboard shortcuts, dark mode, multi-tab chat, copy code blocks with one click, drag-and-drop file upload, syntax highlighting via Shiki/HLJS, Markdown rendering via `marked` or `markdown-it`.
6. **Testable UI.** Component tests with `@testing-library` or Playwright. Visual regression tests with Percy/Chromatic (optional).
7. **Same desktop launch feel.** Click a launcher icon → browser opens to the app. No manual `cd /home/q/projects/crabcakes && python main.py`.

### 3.2 Non-Goals

1. **Multi-user / hosted deployment.** Single-user local app. No auth, no DB, no cloud. (Can be added later if requested.)
2. **Replacing the agent runtime.** The local LLM agent loop stays exactly as-is.
3. **Replacing OpenClaw gateway integration.** WebSocket client remains.
4. **Migrating to a heavyweight SPA framework.** No React + build tooling unless explicitly requested. Vanilla JS + Web Components is sufficient for this app size.
5. **Mobile / responsive design.** Desktop browser only. No touch optimization.
6. **Replacing conversation persistence format.** Disk JSON format stays unchanged.

---

## 4. Target Architecture

### 4.1 Process Topology

**Before (current GTK app):**
```
┌──────────────────────────────────────────────┐
│ main.py — Gtk.Application.run()              │
│   └─ ui/window.py — MainWindow               │
│       ├─ ui/views/* (24 widgets, ~24K lines)  │
│       ├─ ui/handlers/* (event routing)       │
│       └─ agent/runtime.py (in-process thread)│
│           └─ gateway/ (WebSocket client)     │
└──────────────────────────────────────────────┘
```

**After (web UI):**
```
┌──────────────────────────────────────────────┐
│ main.py — uvicorn.run(webui.app)             │
│   └─ webui/server.py — FastAPI app           │
│       ├─ POST /api/chat/send                 │
│       ├─ GET  /api/chat/stream  (SSE)        │
│       ├─ GET  /api/conversations             │
│       ├─ GET  /api/agents                    │
│       ├─ POST /api/agents/{name}/invoke      │
│       └─ ... (REST over 127.0.0.1 only)      │
│   └─ webui/static/ — SPA bundle (HTML+JS+CSS)│
│                                              │
│   Background threads:                        │
│     ├─ agent/runtime.py — unchanged          │
│     └─ gateway/ — unchanged                  │
└──────────────────────────────────────────────┘
         ▲
         │  HTTP + Server-Sent Events
         │  (loopback only)
         ▼
┌──────────────────────────────────────────────┐
│ User's browser: http://127.0.0.1:8765/       │
│   └─ SPA: chat tabs, agent tabs, file tree   │
└──────────────────────────────────────────────┘
```

### 4.2 Component Boundaries

**`webui/server.py` (FastAPI app, ~400 lines)**
- Owns HTTP routing only. No business logic.
- Translates HTTP requests → calls into `agent/runtime.py` (which already runs in a background thread).
- Streams agent responses to browser via Server-Sent Events (SSE) — same wire format as today's gateway-to-UI event stream.
- Strictly bound to `127.0.0.1` (loopback only). External connections refused.

**`webui/static/index.html` (~50 lines)**
- Single HTML file. Mounts the SPA. Loads `app.js` and `app.css`.

**`webui/static/app.js` (~1500 lines, vanilla JS or Preact)**
- Chat tab manager, agent tab manager, message rendering, input toolbar.
- Subscribes to `/api/chat/stream` SSE for live agent responses.
- Renders Markdown via `marked` (~50KB minified) + syntax highlighting via Shiki or highlight.js.
- **No build step.** Plain ES modules. Modern browser native imports.

**`webui/static/app.css` (~500 lines)**
- CSS variables for theming. Light/dark/system themes via `prefers-color-scheme`.
- Layout via CSS Grid + Flexbox. No framework.

**`webui/launcher.py` (~100 lines)**
- On startup, opens default browser to `http://127.0.0.1:8765/`.
- Optional: writes a `.desktop` file for application launchers.
- Optional: registers a tray icon for "show window" action.

### 4.3 What Goes Away

| Removed | Lines | Replacement |
|---|---|---|
| `ui/views/*.py` | ~9,400 | `webui/static/app.js` |
| `ui/handlers/*.py` | ~2,400 | `webui/server.py` |
| `ui/window.py` | ~600 | `webui/launcher.py` (50 lines) |
| `ui/wiring.py` | ~120 | Direct function calls in `webui/server.py` |
| `ui/toolbar.py` | ~200 | HTML `<toolbar>` element |
| `ui/constants.py` + `ui/styles.py` | ~400 | CSS + JSON constants in `app.js` |
| `utils/escaping.py` | ~300 | Browser DOM (no escape needed) |
| `utils/markdown.py` | ~150 | `marked` library in browser |
| `utils/gtk_safe_link.py` | ~80 | `<a target="_blank" rel="noopener">` |
| `utils/css_provider.py` | ~50 | CSS file |
| `main.py` GTK bootstrap | ~56 | `uvicorn.run()` (5 lines) |
| **Total removed** | **~13,800** | |
| **Total added** | | **~3,500** |
| **Net delta** | | **-10,300 (-75%)** |

### 4.4 What Stays Exactly The Same

- `agent/runtime.py` (3,178 lines) — **zero changes**
- `agent/tools.py` (892 lines) — **zero changes**
- `agent/special_agents.py` — **zero changes**
- `agent/config.py` — **zero changes**
- `agent/context.py` — **zero changes**
- `agent/enforcement.py` — **zero changes**
- `gateway/*.py` — **zero changes**
- `models/*.py` — **zero changes**
- `utils/providers_store.py`, `utils/agent_defs.py`, `utils/git_ops.py`, etc. — **zero changes**
- `prompts/`, `knowledge/` — **zero changes**
- Conversation JSON format on disk — **zero changes**
- OpenClaw gateway WebSocket protocol — **zero changes**
- `~/.config/crabcakes/conversations/*.json` — backward compatible

---

## 5. Implementation Plan

Five phases, each independently shippable. **No phase requires the prior phase to be merged** — the GTK app remains functional until Phase 4 ships.

### Phase 1: Parallel FastAPI Server (1 week)

**Goal:** Stand up a FastAPI server that exposes a single read-only endpoint, alongside the running GTK app. Proves the bridge pattern works.

**Deliverables:**
- `pyproject.toml` adds `fastapi>=0.110`, `uvicorn[standard]>=0.27`. (No removal of `PyGObject` yet.)
- New `webui/server.py` (~150 lines) with one endpoint: `GET /api/health` returns `{"status": "ok"}`.
- `webui/static/index.html` (~20 lines) returns "Hello from FastAPI".
- Bind to `127.0.0.1:8765` only. Refuse external connections.
- Manual test: start GTK app + start FastAPI via separate terminal. `curl http://127.0.0.1:8765/api/health` returns OK. Browser shows hello page.

**Done when:** Both processes can run simultaneously without conflict. GTK app still functional.

### Phase 2: Read-Only API Mirroring GTK State (2 weeks)

**Goal:** FastAPI server can serve the same data GTK shows, but only reads. GTK is still the primary UI.

**Deliverables:**
- `GET /api/conversations` — list all sessions + metadata
- `GET /api/conversations/{key}` — full conversation with messages
- `GET /api/agents` — list configured agents
- `GET /api/projects` — list project groups
- `GET /api/feed` — feed events from `.crabcakes/feed.json`
- Read-only SPA page in browser that displays the same info as GTK. Ugly is fine — this is a smoke test.
- Add SSE endpoint `GET /api/events` that streams a heartbeat (proves SSE works).

**Done when:** Browser shows accurate snapshot of every conversation, agent, and project that GTK shows. SSE heartbeats appear in browser console.

### Phase 3: Bidirectional — Web UI Can Send Messages (2 weeks)

**Goal:** Web UI can send messages to any agent. GTK still works.

**Deliverables:**
- `POST /api/conversations/{key}/messages` — enqueue user message
- `POST /api/agents/{name}/invoke` — invoke a special agent (Coder, Debugger)
- SSE event stream: `POST /api/conversations/{key}/stream` returns SSE that emits `text_delta`, `tool_call`, `tool_result`, `done`, `error` events. **This is the same event schema the GTK `chat_render_handler.py` already consumes.**
- Refactor: extract `agent/runtime.py`'s event emission into a transport-agnostic `EventBus` class that both GTK handler and FastAPI SSE handler subscribe to. (No behavior change for GTK.)
- SPA gets a working chat input → see live streaming response in browser.

**Done when:** Can hold a full conversation in the browser with any agent. Existing 118 tests still pass. GTK app unchanged.

### Phase 4: Feature Parity + GTK Removal (3 weeks)

**Goal:** Web UI has feature parity with GTK for every documented use case. GTK code is removed.

**Deliverables:**
- All GTK features ported: prompt library, agent discovery, project browser, project group chat, membership toggles, agent builder, settings dialog, review layer (diff viewer), feed cards, activity drawer, image viewer, audio recorder.
- SPA component library extracted (chat bubble, agent card, tool result card, file tree, diff viewer).
- `utils/escaping.py`, `utils/markdown.py`, `utils/gtk_safe_link.py`, `utils/css_provider.py` — marked deprecated, scheduled for removal in Phase 5.
- `pyproject.toml` removes `PyGObject` dependency. `ui/` directory deleted.
- `main.py` rewritten as 5-line `uvicorn.run()` entrypoint.
- `crabcakes.desktop` file generated for Linux app launchers (browser auto-opens to `127.0.0.1:8765`).

**Done when:** `python main.py` starts FastAPI server and opens browser. GTK app no longer in repo. All existing tests pass (the GTK-touching tests are deleted or converted to web tests).

### Phase 5: Polish + Dead Code Removal (1 week)

**Goal:** Clean up. Improve test coverage on the new web layer.

**Deliverables:**
- Delete `ui/` (already gone after Phase 4). Delete `utils/escaping.py`, `utils/markdown.py`, `utils/gtk_safe_link.py`, `utils/css_provider.py`.
- Add Playwright component tests for the SPA (chat send/receive, agent invocation, conversation load, file tree nav, diff viewer).
- Add FastAPI integration tests using `httpx.AsyncClient` against `TestClient`.
- Update `docs/ARCHITECTURE.md` Section 2 (directory structure) and Section 11 (file inventory).
- Update `docs/PRODUCT_VISION.md` "What's Built" section: replace "GTK4 Port ✅" with "Web UI ✅".
- Update `README.md` install instructions: remove `apt install libgtk-4-1` etc.

**Done when:** `pip install -e .` works on a fresh Ubuntu/Debian box without system packages. CI passes. `pytest` runs in <60s.

---

## 6. Technical Decisions

### 6.1 Why FastAPI (not Flask, not Starlette, not aiohttp)

| Criterion | FastAPI | Flask | Starlette | aiohttp |
|---|---|---|---|---|
| Async-native | ✅ | ❌ (needs Quart) | ✅ | ✅ |
| Built-in SSE | ✅ (StreamingResponse) | ❌ (manual) | ✅ | ❌ (manual) |
| Type hints / Pydantic | ✅ | ❌ | ❌ | ❌ |
| OpenAPI docs auto-gen | ✅ | ❌ (needs flask-restx) | ❌ | ❌ |
| Hot reload in dev | ✅ (`--reload`) | ❌ | ✅ | ❌ |
| Mature, well-maintained | ✅ (Tiangolo) | ✅ | ✅ | ✅ |
| LoC for "hello world" | 5 | 5 | 10 | 15 |

FastAPI wins on async + SSE + type safety. The Pydantic models also document the API contract for free.

### 6.2 Why Vanilla JS + Web Components (not React, not Vue, not Svelte)

The current GTK UI has 14 major widget types. Vanilla JS + Web Components handles this with zero build step.

| Criterion | Vanilla JS + WC | React + Vite | Vue 3 | Svelte |
|---|---|---|---|---|
| Build step required | ❌ | ✅ | ✅ | ✅ |
| Bundle size | ~5KB | ~140KB | ~80KB | ~30KB |
| Time to first interaction | Instant | Build + bundle | Build + bundle | Build + bundle |
| Learning curve | Zero (it's just JS) | Moderate | Moderate | Low |
| Hot reload during dev | Native (refresh browser) | ✅ (Vite HMR) | ✅ | ✅ |
| Test framework | `@web/test-runner` | Vitest + RTL | Vitest | Vitest |
| "Where is this state?" | Same as GTK: in DOM | React state hooks | Vue refs | Stores |

**Counter-argument:** If the Captain prefers a component framework, swap to **Preact** (3KB, React-compatible API). It's a 2-hour swap from vanilla, not a 2-week rewrite.

**Final decision:** Vanilla JS + Web Components for V1. Preact migration is a tractable Phase 6 stretch goal if needed.

### 6.3 Why SSE (not WebSocket, not long-polling)

The current agent runtime emits events from `agent/runtime.py` to GTK handlers via a custom in-process callback (`self._dispatch(self._on_text_delta, ...)`). For the web UI, we need to ship these events to the browser.

| Transport | Bidirectional | Server-push complexity | Browser API | Reconnect logic |
|---|---|---|---|---|
| **SSE** | One-way (server→client) | Trivial | `EventSource` | Built-in |
| WebSocket | Bidirectional | Moderate | `WebSocket` | Manual |
| Long-poll | One-way | High | `fetch` + recursion | Manual |
| gRPC-Web | Bidirectional | High | Library needed | Library needed |

We **only need server→client push** (the client sends messages via separate POST). SSE is the perfect fit. It's also debuggable in browser DevTools (Network tab shows the stream). Reconnects are automatic. No library needed.

### 6.4 Why Loopback-Only Binding (not auth)

The Captain is the only user. The app runs on their laptop. Binding to `127.0.0.1` (not `0.0.0.0`) means no other machine on the network can reach the server. This is the standard local-app pattern (VS Code, Cursor, Postman, Insomnia all do this).

**If multi-user access is ever needed:** add bearer token auth + bind to `0.0.0.0`. Out of scope for this proposal.

### 6.5 Why Single-File `index.html` + ES Modules (not bundled)

Modern browsers support `<script type="module" src="...">` natively. The SPA loads as:
1. `index.html` (50 lines) — defines `<app-root>` and imports `app.js`
2. `app.js` (1500 lines) — imports components from `components/*.js`
3. `components/chat-bubble.js`, `agent-card.js`, etc. (~50 lines each)

No Webpack, no Vite, no Rollup. Just files. Edit a file, refresh browser, see change. This matches the existing crabcakes "small scripts, no build step" ethos.

**Counter-argument:** ES modules in browsers have CORS rules that fail when loading from `file://`. But we're serving from FastAPI on `http://`, so this isn't an issue.

---

## 7. Security Considerations

### 7.1 Threat Model (unchanged from GTK app)

The current GTK app runs arbitrary `exec_command` tool calls with PM approval. **The web UI does not change this threat model.** The browser is just a different rendering surface — all tool execution happens in `agent/runtime.py`, gated by the same approval flow.

### 7.2 New Attack Surface

| Risk | Mitigation |
|---|---|
| XSS via agent text containing `<script>` tags | Use `textContent` for raw text, `innerHTML` only for sanitized Markdown output via `DOMPurify`. |
| CSRF (cross-site request to localhost) | Bind to `127.0.0.1` only. Browser same-origin policy blocks cross-site POSTs to `127.0.0.1` (different origin from attacker.com). Additionally, set `Access-Control-Allow-Origin: http://127.0.0.1:8765` only (no wildcard). |
| Local privilege escalation via arbitrary file reads | Same as GTK app: file reads go through `read_file` tool which respects project boundaries. No new file system access introduced. |
| Conversation privacy | Conversations stay in `~/.config/crabcakes/conversations/*.json`. Web UI reads them via API; same as GTK did directly. No new persistence. |
| Token theft via DevTools | API keys stay in `providers.yaml` on disk. Web UI never receives them — it calls FastAPI which calls the LLM SDK. (Same security posture as GTK.) |
| Denial of service via runaway stream | FastAPI has built-in timeout middleware. SSE connections auto-close after 5 minutes idle. |
| Browser fingerprinting | N/A — this is a single-user app. |

### 7.3 No External Network Exposure

The web server binds to `127.0.0.1` only. Verified at startup:
```python
assert server_config.host == "127.0.0.1", "Refusing to bind to non-loopback"
```

If anyone tries to expose it via `ngrok` or `tailscale`, that's their explicit choice and not enabled by default.

---

## 8. Migration & Rollback Strategy

### 8.1 Coexistence During Phases 1-3

GTK and FastAPI run **simultaneously**. They share the on-disk conversation files (read-only during Phase 2, read-write during Phase 3 via file locks). GTK remains the primary UI for daily use. FastAPI is a parallel experimental surface.

**Conflict scenario:** GTK saves a conversation while FastAPI reads it. Solution: FastAPI uses `fcntl.flock(LOCK_SH)` for reads, `LOCK_EX` for writes. GTK's existing `_save_conversation_to_disk` already acquires `LOCK_EX`. So writes are serialized. Reads see consistent state.

### 8.2 Cutover (Phase 4)

`main.py` becomes:
```python
import uvicorn
from webui.server import app
from webui.launcher import open_browser

if __name__ == "__main__":
    open_browser("http://127.0.0.1:8765/", delay=1.5)  # let server start
    uvicorn.run(app, host="127.0.0.1", port=8765)
```

`pyproject.toml` swaps `PyGObject>=3.48` for `fastapi>=0.110` + `uvicorn[standard]>=0.27`.

**Rollback:** `git revert` the Phase 4 commit. Restores GTK. Conversation files are unchanged. ~30 seconds of downtime.

### 8.3 Data Migration

**None required.** Conversation format is JSON. GTK and FastAPI both read/write the same `~/.config/crabcakes/conversations/{session_key}.json`. No transformation needed.

Settings (providers.yaml, agent.yaml, prompts/*.md) live on disk and are read by both UIs identically.

---

## 9. Success Criteria

### 9.1 Phase 1 success
- [ ] `curl http://127.0.0.1:8765/api/health` returns `{"status": "ok"}` from a fresh shell.
- [ ] Browser shows "Hello from FastAPI" page.
- [ ] `curl http://192.168.x.x:8765/api/health` (external IP) returns connection refused.
- [ ] All 118 existing agent runtime tests still pass.

### 9.2 Phase 4 success
- [ ] `pip install -e .` on a fresh Ubuntu 24.04 box completes without `apt install` commands.
- [ ] `python main.py` opens a browser tab to the chat UI.
- [ ] All 118 existing tests pass.
- [ ] Can send a message to Coder and receive a streaming response in the browser.
- [ ] Can view, edit, and persist a conversation. JSON on disk is unchanged.
- [ ] Can invoke all 8 hardcoded tools (`read_file`, `write_file`, `exec_command`, `search_files`, etc.) through the UI.
- [ ] All Pango-related bugs from the past 6 months are no longer reproducible (because Pango is no longer involved).
- [ ] Total LoC under `webui/` is ≤5,000 lines.
- [ ] Total LoC removed from `ui/` + `utils/escaping.py` + `utils/markdown.py` + `utils/gtk_safe_link.py` is ≥10,000 lines.

### 9.3 Long-term success (3 months post-cutover)
- [ ] Zero Pango-related bug reports.
- [ ] Time-to-fix for "agent text rendered wrong" bugs drops from hours to minutes (just edit the Markdown component).
- [ ] Install-on-fresh-machine time drops from ~10 minutes (apt + pip) to ~30 seconds (just pip).
- [ ] No regressions in agent runtime metrics (success rate, latency, token cost).

---

## 10. Risks & Open Questions

### 10.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Port effort is larger than estimated** | Medium | High | Phases are independently shippable. Each phase delivers value. Can stop after Phase 3 and have a read-mostly web UI alongside GTK. |
| **Browser-only workflow is unacceptable to user** | Low | High | GTK rollback path is one `git revert`. Keep GTK branch alive for 3 months post-cutover as safety net. |
| **Markdown rendering differs from Pango in subtle ways** | Medium | Low | Visual regression tests compare before/after screenshots. Document any intentional differences (e.g., `***bold-italic***` is now standard Markdown). |
| **Performance regression** (browser overhead) | Low | Medium | Profile with Lighthouse. SSE is native to browser. Modern Chromium has <5ms overhead vs. GTK for text rendering. |
| **Browser security prompts** (mixed content, etc.) | Low | Low | We serve over plain HTTP on localhost. No HTTPS needed. No mixed content because no external resources. |
| **Loss of GTK-specific affordances** (global hotkeys, system tray) | Medium | Low | Phase 4 includes a minimal `webui/launcher.py` tray icon. Hotkeys are handled by browser via `Ctrl+Enter` etc. |
| **Existing tests rely on GTK mocks** | High | Low | Tests are written against `agent/runtime.py`, not GTK. GTK-touching tests are removed in Phase 5. Already-covered behavior is unaffected. |
| **Conversation file format needs to evolve** | Low | Low | Out of scope. If needed, additive migration. |

### 10.2 Open Questions for the Captain

1. **Vanilla JS or Preact?** Vanilla is zero-build-step but limits componentization. Preact adds 3KB but unlocks ergonomic patterns. Default: vanilla. Override if you have a preference.
2. **Dark mode required?** Default: yes (CSS `prefers-color-scheme`). Override if you want a fixed theme.
3. **System tray icon?** Default: yes (Phase 4 includes `pystray` integration for "show window" action). Override if you don't want a tray icon.
4. **Browser auto-open on launch?** Default: yes (`webbrowser.open()` after 1.5s delay). Override if you want to launch without auto-opening.
5. **Port 8765?** Default: yes (arbitrary unused port). Override if you have a preference.
6. **What about the `crabcakes-logo.jpg` and `icons/`?** Used by GTK for window icons and app launcher. Default: keep on disk, browser uses favicon. Override if you want them removed.
7. **What about `pyrightconfig.json` and `pytest.ini`?** No change needed. Same Python module layout.
8. **What about the `crabcakes.desktop` file?** Default: auto-generate on first run, install to `~/.local/share/applications/`. Override if you want a different launcher.
9. **What about the existing `webui/` proposal in the repo?** None exists. This is a new directory.
10. **What about the `prompts/` system prompts?** No change. They're loaded by `agent/runtime.py` at startup. Web UI doesn't see them.

---

## 11. Effort Estimate (lines of code)

| Phase | Backend | Frontend | Tests | Total | Calendar |
|---|---|---|---|---|---|
| 1: Hello world FastAPI | 150 | 50 | 0 | 200 | 1 week |
| 2: Read-only API | 400 | 400 | 100 | 900 | 2 weeks |
| 3: Bidirectional + SSE | 600 | 800 | 300 | 1,700 | 2 weeks |
| 4: Feature parity + GTK removal | 800 | 2,500 | 800 | 4,100 | 3 weeks |
| 5: Polish + dead code removal | 200 | 200 | 600 | 1,000 | 1 week |
| **Total** | **2,150** | **3,950** | **1,800** | **7,900** | **9 weeks** |

Of which **2,400 lines** are deletions of `ui/handlers/`, **9,400 lines** are deletions of `ui/views/`, and **~600 lines** are deletions of `utils/escaping.py` + `utils/markdown.py` + `utils/gtk_safe_link.py` + `utils/css_provider.py`. **Net delta: ~-7,500 lines.**

---

## 12. Alternatives Considered

### 12.1 Stay on GTK, fix Pango bugs as they come

**Pros:** Zero migration risk. Familiar to current developers. No new testing infrastructure.
**Cons:** Bug class is structural — every LLM output that contains HTML-like syntax will trigger regressions. The `utils/escaping.py` + `utils/markdown.py` regex chain is fundamentally fragile. Estimated 1 Pango-related bug every 2-4 weeks ongoing.

**Verdict:** Rejected. This is the "death by a thousand cuts" path. The existing `PROPOSAL-fix-malformed-pango-markup.md` (shipped) did not prevent today's incident.

### 12.2 TUI via Textual

**Pros:** Pure Python. No browser dependency. Native terminal aesthetics. Markdown rendering via Rich.
**Cons:** Doesn't help with images, audio recording, code diff visualization, drag-and-drop file uploads. Some Captain workflows (image attachment, voice notes) require a richer surface. Limited window management.

**Verdict:** Rejected as primary, valid as Phase 6 stretch goal for power users. Textual and Web UI are not mutually exclusive — could add a `crabcakes tui` subcommand.

### 12.3 Qt / KDE (PyQt6 or PySide6)

**Pros:** More robust than GTK. Better documentation. Cross-platform.
**Cons:** Still a desktop widget toolkit — same fundamental problem (escape layer + markup fragility, just with HTML subset instead of Pango). Heavier dependency than GTK. License complications for PySide6 (LGPL).

**Verdict:** Rejected. Doesn't solve the structural problem. Just trades one widget toolkit for another.

### 12.4 Electron / Tauri

**Pros:** Web UI in a native shell. Tauri is small (~10MB binary).
**Cons:** Electron is 200MB+ and slow. Tauri requires Rust toolchain for build. Both add complexity without solving the "running app is now a browser" reality.

**Verdict:** Rejected. Browser IS already the web UI. No reason to wrap it in another shell. (If the Captain wants app-mode without browser chrome, that's a Phase 7 "Electron-lite wrapper" stretch goal.)

### 12.5 Keep GTK, migrate to a different renderer (WebKitGTK)

**Pros:** Lets you write the UI in HTML/CSS/JS while keeping a GTK window chrome.
**Cons:** WebKitGTK is finicky. Doesn't solve the underlying "two renderers" problem (Pango for chrome, HTML for content). Maintenance burden is similar.

**Verdict:** Rejected. Half-measure. If we're going to HTML/CSS, do it directly in a browser.

---

## 13. Implementation Order (Recommended)

```
Week  1  2  3  4  5  6  7  8  9
      ├──Phase 1──┤
            ├──Phase 2──────┤
                  ├──Phase 3──────┤
                        ├──Phase 4──────────┤
                                    ├──Phase 5──┤
```

Each phase ends with a demoable artifact. The Captain can stop after any phase and have a working system.

---

## 14. References

- `docs/ARCHITECTURE.md` — current architecture (will need Section 2 + 11 updates in Phase 5)
- `docs/PRODUCT_VISION.md` — "What's Built" section needs updating in Phase 5
- `docs/proposals/PROPOSAL-fix-malformed-pango-markup.md` — the existing partial fix this proposal supersedes
- `docs/proposals/PROPOSAL-agent-package-restructure.md` — orthogonal refactor (extract `agent/` god package), can run in parallel
- `docs/THREAT_MODEL.md` — security review will need an addendum for the new web surface
- FastAPI docs: https://fastapi.tiangolo.com/
- SSE spec: https://html.spec.whatwg.org/multipage/server-sent-events.html
- `marked` library: https://marked.js.org/

---

## 15. Decision Requested

Approve, reject, or modify this proposal. Specific approvals requested:

1. **Approve Phase 1** (1 week, hello-world FastAPI server) as a low-risk proof of concept.
2. **Confirm framework choice**: FastAPI + vanilla JS + SSE (vs. the alternatives in §12).
3. **Confirm phasing**: 9-week roadmap with GTK rollback safety net through Phase 4.
4. **Confirm non-goals**: no multi-user, no auth, no mobile, no Electron wrapper in V1.

If approved, Phase 1 starts immediately. First deliverable: a FastAPI server running on `127.0.0.1:8765` returning `{"status": "ok"}` alongside the existing GTK app.