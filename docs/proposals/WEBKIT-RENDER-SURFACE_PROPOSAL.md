# PROPOSAL: WebKit Render Surface — the agent speaks HTML

**Date:** 2026-09-15
**Author:** Lt. Qrusher, per PM direction
**Status:** Proposal — for PM review. Nothing implemented; no code changed.
**Target branch:** main
**Supersedes the premise of:** `docs/specs/SPEC-UI-RESPONSIVENESS-3.md` §4 (feed virtualization)

---

## 1. The idea

Replace the GTK/Pango widget-assembly path for **message and card content** with a single `WebKit.WebView`
per pane. The agent emits an HTML fragment; the WebView renders it. JavaScript stays **enabled**, so a card
can be interactive — click A or B, tick boxes, edit a field, hover a chart — and post the user's answer back
into the app as structured data.

The app keeps its GTK shell (tabs, project tree, diff viewer, editors, approval dialogs). What it stops doing
is hand-building thousands of widgets and Pango markup to draw text.

**Framing that matters:** this is not a browser. It is a local, private render surface for one document the
app itself supplies. There is no origin model, no navigation, no third-party content, no cookies to steal.
That is why the usual sanitizer theatre does not apply — and the two rules in §5 are the whole security story.

---

## 2. Why (measured, not vibed)

**The main thread is pinned, and it is entirely Pango/layout.** `py-spy dump --native` on the live app:

```
g_main_context_iteration → g_signal_emit → g_closure_invoke
  → gtk_widget_allocate   (~12 nested frames)
    → gtk_layout_manager_measure
      → pango_layout_get_size → g_utf8_strlen
```

`scripts/crab_perf_probe.py`, three runs on two app instances, zero-to-ten card arrivals each:

| run | mean | median | p90 | max |
|---|---|---|---|---|
| 120s | 82.5% | 100% | 100% | 103.4% |
| 180s | 61.9% | 98.3% | 100% | 101.4% |
| 120s | 38.4% | 22.4% | 99.8% | 100.6% |

Every other thread was idle at dump time. The gate in `SPEC-UI-RESPONSIVENESS-3` §7 is **mean < 20%**.
A month of spec work (UIRESP-1 → 2 → 3, 21 documents, ~4,000 lines) has not cleared it, because each
spec tuned the Python side around a cost that lives in GTK.

**The code being defended.** `ui/views/chat_bubble.py` (1,112 lines), `ui/views/feed_card.py` (898),
`ui/handlers/chat_render_handler.py` (858), plus `utils/markdown.py`, `utils/escaping.py`,
`utils/syntax_highlight.py` — markdown and syntax highlighting are converted to Pango markup and stuffed
into labels. 68 test files touch these modules.

**Memory is going the wrong way too.** RSS 897 MB → 2,177 MB over ~7 h on one instance; 1.2 GB in 41 min on
the next. `/proc/<pid>/smaps`: ~1.06 GB of it is anonymous heap — object accumulation, not file mappings.
The feed data itself is *not* the cause: loading all 14,275 eagledispatch cards through the app's own
`feed_store.load_feed` costs ~40 MB traced / ~125 MB RSS peak.

---

## 3. What changes

| Today | Proposed |
|---|---|
| `Gtk.Label` + Pango markup per bubble/card, built in Python | One `WebKit.WebView` per pane; content is HTML/CSS |
| markdown → Pango, highlight → Pango | markdown → HTML (or the agent emits HTML directly) |
| 15-card page + backlog widget churn | the engine scrolls and lays out; nothing to virtualize |
| text layout on the GTK main thread | layout in WebKit's own web process |

**Stays GTK:** tab bar, project tree/left panel, diff viewer, editors, session menus, and every native
approval dialog.

**Verified on this machine already** (app interpreter, `/usr/bin/python3` 3.12):
`libwebkitgtk-6.0.so.4.16.7` + `WebKit-6.0.typelib` are installed; GTK4 and WebKit 6.0 co-import cleanly;
`WebKit.WebView` **is** a `Gtk.Widget`, so it drops into the existing widget tree; JS defaults on
(`enable-javascript: True`, `enable-javascript-markup: True`).

---

## 4. The bridge (proven end-to-end)

A card rendered by an agent, with JS enabled, whose button click reached Python as structured data. Measured
output from the working demo: `{"value":"B","card_id":"card-1","type":"choice"}`.

**Python side:**

```python
ucm = WebKit.UserContentManager()
ucm.register_script_message_handler("crabcakes", None)      # page → app
ucm.connect("script-message-received::crabcakes", on_message)  # payload.to_json(0)

view = WebKit.WebView(user_content_manager=ucm)             # a Gtk.Widget
view.get_settings().set_property("enable-javascript", True)
view.evaluate_javascript("someJs()", -1, None, None, None, None, None)  # app → page
```

**Page side (what the agent writes):**

```html
<button onclick="window.webkit.messageHandlers.crabcakes
                 .postMessage({type:'choice', card_id:'card-1', value:'A'})">Option A</button>
```

JS runs in WebKit's sandboxed web process: no filesystem, no Python objects, no direct access to the app.
The message handler above is the *only* channel back.

**Message types the handler should accept (allowlist, extensible by PM):**

| type | payload | app action |
|---|---|---|
| `choice` | `card_id`, `value` | inject as that session's next user turn (or record on the card) |
| `form` | `card_id`, `fields{}` | same, as a structured user turn |
| `open` | `path` | focus the file in the tree / diff viewer |
| `request_exec` | `cmd`, `card_id` | **must** go to the native approval dialog (§5) |

Anything not on the list is dropped and logged.

---

## 5. The two rules (the entire security posture)

The page is local and private — one document, no navigation, no external content. Over-filtering would only
mangle the agent's output. Two rules, and their reason:

1. **No network from the page.** Block external subresource loads and page-initiated fetches. The agent's
   card often renders text the agent did *not* author — file contents, tool output, search results. With the
   outbound channel closed, injected content is stuck inside the card and cannot exfiltrate.
2. **The handler treats every message as a request, never a command.** Anything consequential (run a command,
   write a file, approve a tool) routes through the same native approval card the agent's `exec_command`
   already uses. The page can never approve itself. This is the only difference that matters between "the
   agent asked" and "a page decided".

Explicitly **not** proposed: an HTML sanitizer that strips the agent's formatting, CSP gymnastics, or turning
JS off. With the two rules in place, JS-on costs nothing that is worth having.

---

## 6. What this deletes / de-scopes

- The Pango markup path for transcript and feed content: `chat_bubble.py`, `feed_card.py` widget assembly,
  `utils/markdown.py`, `utils/escaping.py`, `utils/syntax_highlight.py` (subject to §2 evidence, not dogma).
- The 15-card page/backlog rendering strategy.
- **`SPEC-UI-RESPONSIVENESS-3` §4** ("bound rendered cards / virtualize") becomes moot — the widget tree it
  proposes to virtualize stops existing. Phases 1–2 stay shipped and harmless.
- The 188-test feed-handler suite's widget-path coverage needs rework — this is the main cost, not the code.

---

## 7. Risks and unknowns (honest list)

| Risk | Note |
|---|---|
| Memory | WebKit is heavy, but out-of-process: the app's 1–2 GB heap should drop while another process grows. **Unproven** — must be measured. |
| Sizing/scrolling | A WebView inside a scrolled transcript needs either one document per pane, or JS-reported content heights. Real plumbing. |
| Theming | Needs an injected house stylesheet so agent output looks like Crabcakes, not 47 whims. Recommend a small `ph-*` class grammar (Phosphor's precedent). |
| Failure mode | The agent can emit broken HTML. Needs a plain-text fallback render path. |
| Tests | 68 test files touch the modules being replaced. |
| Sandbox | WebKit's sandbox needs working `bwrap` in production. (In my headless Xvfb test it had to be disabled; that is a test-environment artifact, not a design choice.) |

---

## 8. Proposed spike (one page, no phases)

Swap **the chat transcript pane only**. JS on. No network. One message type (`choice`) routed to a log line.
Everything else stays GTK.

**Acceptance gate — measured, not vibed:** `scripts/crab_perf_probe.py` reports **mean < 20%** with the
transcript holding ≥3,500 messages, idle *and* during an active agent turn. Secondary: RSS across a 30-minute
session compared against today's ~900 MB → 2 GB curve.

Only if the gate is cleared does the feed pane follow.

---

## 9. Open questions for the PM

1. Chat transcript first, or feed pane first?
2. House CSS grammar — reuse Phosphor's `ph-*` naming, or a Crabcakes-specific set?
3. Do interactive cards get their answer injected as a normal user turn (simplest, fully auditable in the
   transcript) or handled out-of-band as card metadata?
4. Timing: after SPEC-68 lands, or as a parallel spike by a separate session?

---

## 10. References

- Pin evidence: `scripts/crab_perf_probe.py`; `SPEC-UI-RESPONSIVENESS-3.md` §2/§3 (the 84.5% pango share).
- Feed-cost measurement: `utils/feed_store.load_feed` on `eagledispatch/.crabcakes/feed.json`
  (14,275 cards → ~40 MB traced / ~125 MB RSS peak).
- Phosphor precedent (HTML-as-UI, JS re-execution, native approval, injection quarantine):
  `/home/q/projects/phosphor` — `shell.html`, `ios-app/app-shell.html`, `SYSTEM_PROMPT.md`, `runtime/`.
- Working bridge demo (headless, runnable): `/tmp/webkit_bridge_demo.py` — the §4 snippet in full, plus a
  table and a JS-drawn canvas. Run with
  `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1 xvfb-run -a /usr/bin/python3 /tmp/webkit_bridge_demo.py`.
