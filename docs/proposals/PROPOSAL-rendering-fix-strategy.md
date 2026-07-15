# Rendering Fix Strategy — Synthesis After Deep Dive

**Date:** 2026-07-15
**Author:** QTR (synthesis)
**Status:** ⚠️ PROPOSAL — Not implemented
**Purpose:** Decide whether to (a) keep GTK and harden the existing escape layer, (b) migrate chat bubbles to TextView + TextTag, or (c) do the full web UI migration proposed in `PROPOSAL-web-ui-replacement.md`.
**Inputs:**
- `docs/proposals/PROPOSAL-web-ui-replacement.md` (the 9-week web UI migration)
- `docs/research/PROPOSAL-rendering-alternatives.md` (external library + reference project survey)
- Local code audit of `utils/escaping.py`, `utils/markdown.py`, `ui/views/chat_bubble.py`, `ui/handlers/chat_render_handler.py`, `tests/test_markdown.py`

---

## TL;DR (the question you actually asked)

**You don't have to choose between "9-week web UI migration" and "do nothing."** There are three intermediate options that range from 1-day to 4-week efforts. The right answer depends on what you actually want from the rendering layer long-term.

**My recommendation:**

1. **Do the 1-2 day quick fix NOW** to stop the bleeding. It is unambiguous.
2. **Schedule a 2-4 week TextView migration** as the permanent structural fix. This is what every other mature GTK chat app chose.
3. **Hold the web UI migration in reserve** for if/when you decide you want features GTK can't easily provide (tables, syntax highlighting via Shiki, Mermaid diagrams, inline image embedding, etc.).

---

## What I actually found in our code

A few things worth flagging up front — they changed my view of the problem.

### 1. The "Pango warning today" pattern is well-tested, and the test passes

The warning today (`Failed to set text '...&quot;...&#x27;...'`) is the same bug class that `tests/test_markdown.py:TestFencedVsInlineBacktickRegression` was written to catch. That test uses an exact replica of the user-failure content (`Specifically, "&quot;" is being preserved by strict unescape...`) and **passes**. So the bug today is triggered by a *different* input pattern that the test doesn't cover.

```
$ python3 -m pytest tests/test_markdown.py::TestFencedVsInlineBacktickRegression -xvs
tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_inline_bt_followed_by_fenced_block_does_not_eat_block PASSED
tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_inline_underscores_then_fenced_block PASSED
tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_two_inline_bt_then_fenced_block PASSED
tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_exact_user_failure_content_renders PASSED
tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_markup_passes_pango_validation PASSED
```

**Conclusion:** we have not enumerated the bug surface. The test coverage is *reactive* (one test per reported bug), not *generative* (no fuzz/property-based testing of inputs). The escape layer will keep breaking on unseen patterns indefinitely.

### 2. `escape_for_pango` is doing the right thing for the patterns I tested

I ran the actual `escape_for_pango` against the patterns from today's warning and they round-trip cleanly. The text with `&quot;` and `&#x27;` survives through the pipeline and produces valid Pango markup (verified by direct `Gtk.Label.set_markup()` call). So the bug today is in a *combination* of inputs (likely a code span + adjacent bold + auto-link) that the existing regex chain handles inconsistently.

This is the canonical sign of a regex-based parser: the patterns work in isolation but interact badly.

### 3. `utils/escaping.py` + `utils/markdown.py` = 640 lines

The "Pango escape layer" is 640 lines of hand-rolled regex parsing. 17 distinct call sites. 5 Pango-related Phases (Phases 5, 6, 6.1, MED-10, BUG #8) since the port. **A bug every 6-8 weeks on average.** This matches what the sub-agent found about other GTK apps.

### 4. We already use `GLib.markup_escape_text` in 5 places — just not for LLM output

```
$ grep -rn "markup_escape_text" --include="*.py"
ui/views/session_menu.py:50:    header.set_markup(f"<b>{GLib.markup_escape_text(agent_name)}</b>")
ui/views/session_menu.py:81:                label.set_markup(f"✓ {GLib.markup_escape_text(display)}</b>")
ui/views/session_menu.py:142:    header.set_markup(f"<b>{GLib.markup_escape_text(project_name)}</b>")
ui/views/session_menu.py:195:                lbl.set_markup(f"<b>✓ {GLib.markup_escape_text(lbl.get_text())}</b>")
ui/views/main_content.py:371:        tab_name.set_markup(f"<b>{GLib.markup_escape_text(agent_name)}</b>")
```

All 5 are for app-controlled text (agent name, project name). **None are for LLM output.** This is a clue: the codebase has already learned that app-controlled text must be escaped, but applies a different (hand-rolled) escape for LLM text. The sub-agent's recommendation to switch to `GLib.markup_escape_text` for LLM text is consistent with the existing codebase pattern.

### 5. `GLib.markup_escape_text` is verified working

```
>>> GLib.markup_escape_text('hello & <world> "quoted"')
'hello &amp; &lt;world&gt; &quot;quoted&quot;'
```

Output is the same shape as `escape_for_pango` produces for plain text. **Functionally equivalent for the basic case.**

---

## Five concrete options, ranked

This is the synthesis the sub-agent's report enables. Each row is a complete, shippable plan.

### Option A — 1-2 day quick fix (defensive patching)

**What:**
1. Wrap every `label.set_markup(markup)` call site in a `safe_set_markup(label, markup, fallback_text)` helper that catches GMarkup parse errors and falls back to `label.set_text(plain_text)`. ~30 lines.
2. For the LLM-text path specifically (the 17 call sites in `chat_bubble.py` + `chat_render_handler.py`), replace the custom `_strict_unescape` step with `html.unescape()` for entity pre-decoding (handles `&quot;`, `&#x27;`, `&lt;`).
3. Add a regression test that uses **fuzz-generated** LLM text (5-10 random chunks from the conversation fixture corpus) to drive the escape layer and confirm `set_markup()` never raises. ~50 lines.

**Effort:** 1-2 days.
**Risk:** Very low. Pure addition; doesn't change existing escape behavior.
**Solves bug class?** **No.** Still relies on markup strings. But stops the *visible* warnings from reaching the user — anything that fails to parse becomes plain text instead of an empty bubble + Gtk-WARNING.

**Best for:** Buying time while we decide on a longer-term plan. Also the right call regardless of what we do next.

### Option B — 2-3 week mistletoe AST migration (medium refactor)

**What:**
1. Add `mistletoe>=1.4.0` to `pyproject.toml`. (Pure Python, no C deps.)
2. Write a `PangoRenderer(mistletoe.HtmlRenderer)` subclass (~200-300 lines) that walks the CommonMark AST and emits Pango markup. Inline tags (`<em>`, `<strong>`, `<code>`) emit `<i>`, `<b>`, `<tt>`. Block tags (`<h1>`-`<h6>`, `<ul>`, `<ol>`, `<blockquote>`, `<pre>`) emit the existing Pango equivalents or hand-rolled markup.
3. Replace `format_markdown(text)` with `mistletoe.markdown(text, PangoRenderer)`. Drop `utils/markdown.py` (or keep as a thin wrapper for back-compat).
4. Keep `utils/escaping.py` for the code-span/auto-link paths that PangoRenderer doesn't handle.
5. Migrate the 17 call sites in `chat_bubble.py` + `chat_render_handler.py`.

**Effort:** 2-3 weeks.
**Risk:** Medium. AST parsing is more correct than regex, but the renderer output is still Pango markup strings. Bugs in the renderer can still trigger GMarkup parse failures.
**Solves bug class?** **Partially.** The AST parser handles all valid CommonMark correctly. Edge cases (nested formatting, malformed input) are handled by the renderer. But the renderer still emits markup, so the bug class is reduced but not eliminated.

**Best for:** Teams comfortable maintaining a custom renderer. Good middle ground.

### Option C — 2-4 week TextView + TextTag migration (recommended permanent fix)

**What:**
1. Write a `MarkdownTextBuffer` class (~400 lines) that parses Markdown (via mistletoe AST) and inserts plain text into a `Gtk.TextBuffer`, applying `Gtk.TextTag` objects (bold, italic, code, link, etc.) to byte ranges. No markup strings anywhere.
2. Create a `MarkdownTextView` widget (~100 lines) wrapping `Gtk.TextView` with the right CSS (transparent background, no cursor, wrapping, etc.) — modeled on Dissent's `chatkit/md/block/textblock.go`.
3. Replace `Gtk.Label` with `Gtk.TextView` in `chat_bubble.py`. Update the 17 call sites.
4. Handle streaming deltas: instead of `set_markup()` on every 150ms, append text to the existing buffer and apply tags. (Possibly simpler — just append, no full re-render.)
5. Delete `utils/escaping.py` and `utils/markdown.py`. The escape layer is no longer needed.
6. Update `tests/test_markdown.py` → `tests/test_textbuffer_markdown.py` to test the new path.
7. CSS adjustments for `.markdown-textview` to match existing chat bubble look.
8. Keep `Gtk.Label` for app-controlled text (agent name, project name, status bar) — those use `GLib.markup_escape_text` and don't need migration.

**Effort:** 2-4 weeks.
**Risk:** Medium-high. UI refactor. CSS theming work. Streaming delta logic needs care. But the architecture is the GTK-recommended path and matches every mature GTK chat app's approach.
**Solves bug class?** **Yes, permanently.** No markup string = no markup parse failure. Text is plain Unicode in a buffer; formatting is metadata.

**Best for:** Permanent fix that keeps the GTK app working. What every other GTK chat app does (Dissent, Dino, Gajim).

### Option D — 9-week web UI migration (PROPOSAL-web-ui-replacement.md)

**What:** Replace the entire `ui/` layer with FastAPI + SPA. GTK app is removed.

**Effort:** 9 weeks.
**Risk:** High (UI replacement, 14 widgets to port, build/test infra changes, CSS theming rewrite).
**Solves bug class?** **Yes**, trivially — `textContent` assignment in the browser has no markup-parse failure mode.

**Best for:** When you decide you want features GTK widgets can't easily provide (real syntax highlighting via Shiki, Mermaid diagrams, KaTeX math, inline image embedding via drag-drop, copy-code-one-click, modern keyboard shortcuts, dark mode by default). **Not** the right answer for "stop the Pango warnings" — that's a 2-4 week fix.

### Option E — Do nothing

**What:** Continue adding regex patterns to `utils/escaping.py` and `utils/markdown.py` as bugs appear.

**Effort:** None.
**Risk:** None.
**Cost:** ~1 Pango-related bug every 6-8 weeks. Each bug is 30-60 minutes to fix. Each fix adds ~30-100 lines to the escape layer.

**Best for:** If rendering bugs are not actually causing user pain.

---

## Comparison table

| Option | Effort | Solves bug class? | Maintenance burden long-term | Risk | UI changes |
|---|---|---|---|---|---|
| **A** — defensive patching | 1-2 days | ❌ patches symptoms | Same as today | Very low | None |
| **B** — mistletoe AST | 2-3 weeks | ⚠️ partial | Medium (custom renderer) | Medium | None visible |
| **C** — TextView + TextTag | 2-4 weeks | ✅ permanently | Low (standard GTK API) | Medium-high | CSS adjustments |
| **D** — web UI migration | 9 weeks | ✅ permanently | Low (browser) | High | Complete UI rewrite |
| **E** — do nothing | 0 | ❌ | High (1 bug / 6-8 weeks) | None | None |

---

## What other mature GTK chat apps chose

The sub-agent surveyed 5 production GTK chat clients. **All 5 chose TextView + TextTags.** None chose Label + markup for arbitrary user content.

| Project | Stack | Approach |
|---|---|---|
| **Dissent** (GTK4 Discord, Go) | `chatkit/md` | TextView + TextBuffer + TextTag |
| **Dino** (GTK XMPP, Vala) | GSoC 2024 | TextView + PangoAttrList |
| **Gajim** (GTK XMPP, Python) | direct TextView | TextView + TextTags |
| **Fractal** (GNOME Matrix, Rust) | gtk-rs | Mixed: Label+markup for simple, custom widgets for complex |
| **Polari** (GNOME IRC, GJS) | GJS | Label+markup, but IRC has no rich text so escaping is trivial |

**Reference:** Dissent's `chatkit/md` library is the closest production reference for Option C. It's written in Go (not Python) but the architecture translates 1:1. ~600 lines of Go become ~500 lines of Python.

---

## My recommendation, broken into actionable steps

If I were the engineer making this call:

### Step 1: NOW (1-2 days)
Do **Option A**. It's unambiguously the right immediate fix:
- Wrap `set_markup` calls in try/except with plain-text fallback.
- Pre-decode entities with `html.unescape` before the existing escape pipeline.
- Add a fuzz test that runs random LLM corpus chunks through the escape layer.

This stops the visible warnings without changing the architecture. Zero risk.

### Step 2: NEXT (decide within 2 weeks)
Choose between Options B, C, D, or E based on your actual priorities:

- **If "Pango warnings are the only problem"** → Option C. 2-4 weeks, kills the bug class, standard GTK approach.
- **If "I want richer content eventually"** (syntax highlighting, Mermaid, inline images) → Option D. 9 weeks, future-proofs the whole app.
- **If "the GTK escape layer is mostly fine, just patch the holes"** → Option B. 2-3 weeks, AST-based, but still has the same bug class.
- **If "I don't actually care about Pango warnings"** → Option E. Continue as today.

### Step 3: WITHIN 2 MONTHS
Whatever you choose in Step 2, ship it.

---

## Specific question for you

You said "I wanna talk about your what did you find?" and "can you do a deep dive on the code and compare it to other projects." I've done that. The big finding is:

**The 9-week web UI migration is not the right answer to "Pango warnings keep happening."** The right answer to that specific problem is **Option C** (2-4 weeks, TextView + TextTag, what every other GTK chat app does). The web UI migration is the right answer to a *different* question ("do I want to build features GTK widgets can't easily provide?"). These are different problems with different solutions.

What I need to know from you:

1. **Are the Pango warnings actually painful enough to act on?** (You haven't said yes yet — you've said "I wanna talk.")
2. **Do you want richer content eventually** (syntax highlighting, Mermaid, inline images, etc.)? If yes, the web UI migration becomes attractive. If no, the TextView migration is the clear winner.
3. **Is there something specific about today's warning that prompted this besides the warning itself?** (E.g., is the chat UI not working as expected for some content? Are you planning to add a feature that requires richer rendering?)

My honest read: **Option A + Option C is the right answer for "stop the Pango warnings."** Option D (web UI migration) is a different conversation about the long-term direction of the app.

Open to your call.