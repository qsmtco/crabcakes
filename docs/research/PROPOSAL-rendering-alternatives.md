# Rendering Alternatives: Safe LLM Text in GTK4

**Research date:** 2026-07-15  
**Author:** Research sub-agent  
**Status:** For decision

---

## 1. Executive Summary

- **The Pango markup approach is fundamentally fragile for untrusted input.** Every GTK chat app that has tried this path has hit the same wall: `Gtk-WARNING **: Failed to set text from markup`. The bug class is intrinsic to passing user-controlled text through an XML parser (GMarkup) that was never designed for adversarial input.

- **The best long-term alternative is the TextView + TextTag approach** (used by Dissent/chatkit). Instead of building a markup string and parsing it, you insert plain text into a `Gtk.TextBuffer` and apply `Gtk.TextTag` objects (bold, italic, code, etc.) to byte ranges. This **completely eliminates** the markup-parse failure mode because no markup string is ever parsed. It also gives you clickable links, inline images, and spoiler blocks for free.

- **The safest quick fix (1-2 days)** is to replace the hand-rolled escaper with `GLib.markup_escape_text()` on all plain-text segments before passing through `format_markdown()`, and wrap all `set_markup()` calls in try/except to fall back to `set_text()` on parse failure. This patches the bleeding but doesn't cure the disease.

- **WebKitGTK is a non-starter** for CrabCakes. It adds 200-300 MB RAM overhead per WebView instance, requires a heavy system dependency (`webkitgtk6.0` apt package, ~300 MB install), and is architecturally overkill for a chat bubble. It would make sense only if you were building a full web UI migration.

- **No mature Python library exists for Markdown→Pango markup.** The only candidate (`md2pango`) is a JavaScript/GJS project, hasn't been updated in years, explicitly documents itself as "best effort," and recommends WebKitGTK for real richtext. The Python ecosystem has no equivalent. You would have to write one yourself.

---

## 2. Alternatives Investigated

### 2.1 md2pango (JavaScript/GJS)

| Field | Value |
|---|---|
| **URL** | https://github.com/ubunatic/md2pango |
| **Language** | JavaScript (GJS/Node) |
| **Last commit** | ~2022 (sparse activity) |
| **License** | MIT |
| **Maintenance** | Low activity — hobby project |
| **Pango output?** | Yes, direct Pango markup |

**What it is:** A regex-based line-by-line Markdown→Pango converter. Supports headings, bold, italic, code, links, lists, and color macros via HTML comments.

**Pros:**
- MIT license, simple to understand
- Direct Pango markup output
- Small codebase (~200 lines)

**Cons:**
- Written in JavaScript, not Python — would need a full port
- Regex-based, not AST-based — nesting is "unpredictable" per their own README
- Explicitly says: "for true richtext support, use WebKitGTK"
- No support for nested formatting, multi-line list items, or tables
- Still subject to the same GMarkup parse failure on edge cases

**Integration effort:** Medium (port JS→Python, ~2-3 days). But you'd be porting a known-fragile approach.

**Solves the Pango warning bug class?** **No.** It reduces the surface area but still produces Pango markup strings that must be parsed by GMarkup.

---

### 2.2 mistletoe + Custom Pango Renderer (Python)

| Field | Value |
|---|---|
| **URL** | https://github.com/miyuchina/mistletoe |
| **PyPI** | `mistletoe` (v1.4.0, Dec 2025) |
| **License** | MIT |
| **Maintenance** | Active — releases in 2025 |
| **Pango output?** | Not built-in; would need a custom renderer |

**What it is:** A fast, spec-compliant CommonMark Markdown parser in pure Python. Parses to an AST, then renders via swappable renderer classes. Ships with HTML, LaTeX, AST, and Markdown renderers. Custom renderers are trivial to write (subclass `HtmlRenderer`, override `render_strong`, etc.).

**Pros:**
- Proper AST-based parsing — no regex hacks
- Custom renderer architecture is clean and well-documented
- Actively maintained (latest release Dec 2025)
- MIT license
- Pure Python, no C dependencies
- The dev guide (https://github.com/miyuchina/mistletoe/blob/master/dev-guide.md) shows how to create custom renderers with ~30 lines of code

**Cons:**
- No existing Pango renderer — you'd write one (~200-400 lines)
- Still outputs a Pango markup *string*, so GMarkup parse failures remain possible if your renderer has a bug
- Parsing to AST on every chat delta may be slower than current regex approach (though probably negligible)

**Integration effort:** Medium (3-5 days). Write a `PangoRenderer` class, replace `format_markdown()` calls.

**Solves the Pango warning bug class?** **Partially.** The AST parser handles all Markdown correctly, but the output is still a Pango markup string. A bug in the renderer (e.g., not escaping `&` inside an attribute) would still trigger the warning. Much safer than the current regex approach, but not structurally immune.

---

### 2.3 TextView + TextTag Approach (No Markup String) ⭐ Recommended

| Field | Value |
|---|---|
| **Used by** | Dissent (GTK4 Discord client), Dino (GTK XMPP client) |
| **Reference code** | https://github.com/diamondburned/chatkit/tree/main/md |
| **Documentation** | https://pygobject.gnome.org/tutorials/gtk4/textview.html |
| **GTK version** | GTK 4 (works today) |
| **License** | N/A (uses built-in GTK APIs) |

**What it is:** Instead of `Gtk.Label.set_markup("<b>bold</b>")`, you use `Gtk.TextView` + `Gtk.TextBuffer` and apply formatting programmatically:

```python
buffer = textview.get_buffer()

# Create tags once
bold_tag = buffer.create_tag("bold", weight=Pango.Weight.BOLD)
italic_tag = buffer.create_tag("italic", style=Pango.Style.ITALIC)
code_tag = buffer.create_tag("code", family="Monospace")

# Insert text and apply tags to ranges
start_iter = buffer.get_start_iter()
buffer.insert(start_iter, "bold text")

# Apply bold to the inserted range
bold_start = buffer.get_iter_at_offset(0)
bold_end = buffer.get_iter_at_offset(9)  # "bold text" = 9 chars
buffer.apply_tag(bold_tag, bold_start, bold_end)
```

**How Dissent uses it:** Dissent (by diamondburned) uses the `chatkit/md` library, which parses Markdown via goldmark (Go AST parser) and renders it into `Gtk.TextBuffer` with `Gtk.TextTag` objects. The `TextBlock` struct wraps a `Gtk.TextView` and provides methods like `TagBounded(tag, callback)` to apply formatting within a scope. Inline formatting (bold, italic, underline, strikethrough, monospace) maps to named tags. Links use `Gtk.TextTag` with the `activate-link` signal. Spoilers, custom emoji (inline images), and mentions are all handled through TextTags and child anchors.

The key architectural insight from Dissent/chatkit: **the text buffer only ever holds plain Unicode text**. Formatting is applied as metadata (tags) on byte ranges. There is no XML, no Pango markup string, and no GMarkup parser in the path. The "Failed to set text from markup" warning is structurally impossible.

**Pros:**
- **Structurally eliminates the entire bug class.** No markup string = no markup parse failure.
- Handles all Unicode text safely — no escaping needed, ever
- Supports features Pango markup can't: inline images (via child anchors), interactive spoiler blocks, clickable mentions
- Used by production GTK4 chat apps (Dissent has thousands of users)
- Well-documented GTK API, stable since GTK 2
- Tag-based formatting is what GTK itself recommends for "unknown text" per the Pango docs: *"you could create a PangoAttrList and apply it to the text"* (from https://docs.gtk.org/Pango/pango_markup.html)
- Text selection works naturally (unlike Label, where selection is limited)

**Cons:**
- Requires significant refactoring: chat bubbles currently use `Gtk.Label`; switching to `Gtk.TextView` changes the widget hierarchy
- TextTags must be created and managed (though this is straightforward)
- Slightly more verbose than markup strings for simple cases
- `Gtk.TextView` has different CSS theming from `Gtk.Label` — will need CSS adjustments
- No `set_markup()` convenience for static labels (toolbar, status bar, etc.) — though those are low-risk since they display app-controlled text, not LLM output

**Integration effort:** High (1-2 weeks). Requires:
1. Write a `TextBufferRenderer` that walks a Markdown AST (from mistletoe) and inserts text + tags into a TextBuffer
2. Replace `Gtk.Label` with `Gtk.TextView` in chat bubble UI (17 call sites)
3. Create a tag table with standard tags (bold, italic, code, link, etc.)
4. Handle code blocks (separate TextView or styled block within the same buffer)
5. CSS adjustments for transparent background, padding, etc.

**Solves the Pango warning bug class?** **Yes — completely and permanently.**

---

### 2.4 WebKitGTK 6.0

| Field | Value |
|---|---|
| **URL** | https://webkitgtk.org/ |
| **API version** | `webkitgtk-6.0` (GTK 4, since WebKitGTK 2.40) |
| **Python bindings** | Via PyGObject (`gi.require_version('WebKit', '6.0')`) |
| **License** | LGPLv2.1+ (library), BSD (WebKit itself) |
| **Maintenance** | Actively maintained by Igalia and Apple |

**What it is:** Full WebKit rendering engine as a GTK4 widget. You create a `WebKit.WebView`, load HTML into it, and get a full browser rendering with CSS, JavaScript, images, etc.

**Minimal Python code** (from https://github.com/HinTak/minimal-web-browsers):
```python
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('WebKit', '6.0')
from gi.repository import Gtk, WebKit

webview = WebKit.WebView()
webview.load_html("<b>Hello</b> world", "file:///")
# Add webview to your container
```

**Pros:**
- Renders HTML/CSS perfectly — Markdown→HTML is a solved problem
- Handles arbitrary content safely (WebKit's sandbox isolates it)
- Supports JavaScript for interactive content
- Full rich text: tables, images, embedded video, etc.
- Mature, actively maintained, receives security updates

**Cons:**
- **Memory cost: 200-300 MB per WebView instance** (per https://github.com/webview/webview/issues/421). This is on top of CrabCakes' existing memory usage.
- **Install footprint:** The `webkitgtk6.0` apt package is ~50-100 MB download, ~300 MB installed. Not available on minimal/edge systems.
- **Startup latency:** WebKit adds 200-500ms cold-start time for the first WebView.
- **One WebView per chat bubble would be insane** — you'd need a single WebView rendering all messages (like a web chat app), which is a fundamentally different architecture.
- **Theming mismatch:** WebKit renders its own CSS; matching GTK/libadwaita themes requires significant CSS work.
- **Overkill:** We need bold, italic, code, and links. Loading a web browser engine for that is disproportionate.

**Integration effort:** Very High (4-8 weeks). Would require rearchitecting the entire chat view as a single WebView with a bridge between Python and JavaScript.

**Solves the Pango warning bug class?** **Yes**, but replaces it with a completely different architecture and its own complexity.

---

### 2.5 PangoCairo (Render to Cairo Surface)

| Field | Value |
|---|---|
| **Documentation** | https://docs.gtk.org/PangoCairo/pango_cairo.html |
| **Python example** | https://www.cairographics.org/cookbook/pycairo_pango/ |
| **GTK version** | Works with GTK 4 |
| **Maintenance** | Part of Pango core |

**What it is:** Render text directly to a Cairo image surface using `pango_cairo_show_layout()`, then display the resulting image as a `Gtk.Picture` or paint it in a `Gtk.DrawingArea`.

```python
import cairo
import pangocairo

surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 60)
ctx = cairo.Context(surf)
pc = pangocairo.CairoContext(ctx)
layout = pc.create_layout()
layout.set_text("Hello world")
desc = pango.FontDescription("Sans 12")
layout.set_font_description(desc)
pc.show_layout(layout)
```

**Pros:**
- Full Pango rendering control (custom shaping, effects, etc.)
- Can produce images for caching/offline rendering

**Cons:**
- **Text is not selectable** — it's a rendered image
- **No accessibility** — screen readers can't read painted pixels
- **No interactive links** — would need custom hit-testing
- Performance cost: each text reflow requires re-rendering the surface
- **Not recommended in GTK4** — the GTK4 migration guide moved away from Cairo for most use cases. GTK4's rendering is now NGL/Cairo hybrid, and Cairo is considered legacy for widget rendering.
- Significantly more complex than any other approach

**Integration effort:** Very High. Would need custom layout engine, hit-testing, accessibility bridges.

**Solves the Pango warning bug class?** **Yes**, but at the cost of losing text selection, accessibility, and links.

---

### 2.6 GLib.markup_escape_text() + Defensive Fallback (Quick Fix)

| Field | Value |
|---|---|
| **API** | `GLib.markup_escape_text(text)` — C function, exposed via PyGObject |
| **Documentation** | https://docs.gtk.org/glib/func.markup_escape_text.html |
| **Already used** | Yes — in 5 call sites in `session_menu.py`, `main_content.py` |

**What it is:** GNOME's official, C-level function for escaping text for use in Pango markup. Handles `&`, `<`, `>`, `"`, `'`. This is the function that the Jami project (https://git.jami.net/savoirfairelinux/jami-client-gnome/-/issues/444) recommended when they hit the exact same "Failed to set text from markup" bug.

**The fix has two parts:**

1. **Replace custom escaping with `GLib.markup_escape_text()`** for all plain-text segments. This is battle-tested C code that handles all edge cases. The current `utils/escaping.py` has a 302-line hand-rolled implementation that keeps missing cases.

2. **Wrap all `set_markup()` calls in defensive try/except:**
```python
def safe_set_markup(label, markup):
    """Set markup, falling back to plain text on parse failure."""
    try:
        label.set_markup(markup)
    except Exception:
        # GMarkup parse failure — strip all tags and show plain text
        plain = GLib.markup_escape_text(
            re.sub(r'<[^>]+>', '', markup)
        )
        label.set_markup(plain)
```

**Pros:**
- **Minimal code change** — swap function calls, add wrapper
- Uses GNOME's own escaping function, not hand-rolled regex
- The defensive fallback ensures no warning ever reaches the user
- Can be done in a few hours

**Cons:**
- Doesn't fix the root cause — markup strings can still fail to parse
- The fallback to stripped text means users see degraded formatting on edge cases
- Still requires maintaining the 338-line `markdown.py` formatter
- `GLib.markup_escape_text()` only handles XML entities, not the "preserve known Pango tags then escape everything else" logic that CrabCakes needs

**Integration effort:** Low (1-2 days).

**Solves the Pango warning bug class?** **Mostly.** The defensive fallback ensures no warning reaches the user, but formatting may degrade silently. Root cause persists.

---

## 3. How Other GTK Chat Apps Handle This

### Fractal (GNOME Matrix client, GTK4, Rust)

- **Repo:** https://gitlab.gnome.org/World/fractal
- **Language:** Rust (gtk-rs)
- **Approach:** Fractal renders Matrix messages using **Gtk.Label with Pango markup** for simple text, but uses **custom GTK widgets** (not labels) for complex content like images, videos, and formatted text. For HTML messages from Matrix, they parse the HTML and build widget trees. System messages use `Label` with simple escaping.
- **Known issues:** Fractal has had bugs with malformed HTML from Matrix messages. They handle this by falling back to plain text on parse errors.
- **Relevance:** Fractal's approach is similar to CrabCakes' current one (Label + Pango markup), confirming that this path requires constant defensive handling.

### Dino (GTK XMPP client, Vala)

- **Repo:** https://github.com/dino/dino
- **Language:** Vala
- **Approach:** Dino uses a **TextView with TextTags** for message rendering. The GSoC 2024 project "Rich message support for Dino" (https://wiki.xmpp.org/web/Gsoc2024/Dino/Rich_message_support) explicitly describes "Apply markup to messages in conversation history via Pango Attributes" using TextView tags rather than Label markup.
- **Relevance:** **High.** Dino chose the TextView approach over Label+markup, validating Alternative 2.3.

### Gajim (GTK XMPP client, Python)

- **Repo:** https://dev.gajim.org/gajim/gajim
- **Language:** Python
- **Approach:** Gajim uses **Gtk.TextView** for message display with TextTags for formatting. Incoming XHTML-IM (HTML in XMPP) is sanitized and rendered into the TextBuffer. They had a notable bug (#8246) where raw HTML was displayed instead of being rendered — caused by their HTML parser failing on malformed input, falling back to plain text display.
- **Relevance:** **High.** Gajim is the closest analog to CrabCakes (Python GTK chat client). They chose TextView + TextTags.

### Polari (GNOME IRC client, GTK)

- **Repo:** https://gitlab.gnome.org/GNOME/polari
- **Language:** JavaScript (GJS)
- **Approach:** Simple IRC messages — no Markdown or HTML. Uses Label with Pango markup for basic formatting (bold nicknames, links). IRC doesn't have rich text, so the escaping problem is minimal.
- **Relevance:** Low. IRC doesn't face the same content complexity as LLM output.

### Dissent (GTK4 Discord client, Go)

- **Repo:** https://github.com/diamondburned/dissent
- **Library:** https://github.com/diamondburned/chatkit (the markdown rendering layer)
- **Approach:** **TextView + TextBuffer + TextTags**, using goldmark (Go Markdown parser) → AST → chatkit/md renderer → Gtk widgets. Custom renderers for Discord-specific features (mentions, emoji, spoilers). Tags are created from a shared `TextTagTable`. Links use the `activate-link` signal.
- **Key code:** `chatkit/md/mdrender/mdrender.go` — the renderer walks the AST and inserts text + tags. `chatkit/md/block/textblock.go` — wraps `Gtk.TextView` with helpers for tag application.
- **Relevance:** **Highest.** Dissent faces the exact same problem (arbitrary Markdown from Discord users, rendered in GTK4) and chose the TextView approach. Their chatkit library is a reference implementation for the approach recommended in this report.

---

## 4. Known Footguns and Lessons

### The "Failed to set text from markup" bug family

This warning has been reported across dozens of GTK apps over 15+ years:

- **Jami (GTK client):** https://git.jami.net/savoirfairelinux/jami-client-gnome/-/issues/444 — "text formatted using pango markup needs to be escaped." Fix: use `g_markup_escape_text()`.
- **Celluloid (formerly gnome-mpv):** https://github.com/gnome-mpv/gnome-mpv/issues/192 — "Failed to set text '<' from markup." Caused by filenames containing `<`.
- **Waybar:** https://github.com/Alexays/Waybar/issues/240 — ESSID not escaped before Pango interpretation. Network SSIDs containing `&` broke the widget.
- **Zenity:** https://bugs.launchpad.net/bugs/387536 — "Failed to set text from markup due to error parsing markup." Led to a request for a "disable markup" flag.
- **GNOME Bugzilla #386412:** Hyperlink text containing `<` caused markup parse failure.

**Pattern:** Every app that passes external text through `set_markup()` eventually hits this bug. The GNOME community's consistent recommendation is either (a) use `g_markup_escape_text()`, or (b) don't use markup at all for untrusted text.

### Pango markup limitations (from official docs)

Per https://docs.gtk.org/Pango/pango_markup.html:
- Pango uses **GMarkup** (GLib's XML parser) to parse markup
- GMarkup is a **strict** XML parser — malformed XML causes a hard error
- The convenience tags are: `<b>`, `<i>`, `<u>`, `<s>`, `<tt>`, `<big>`, `<small>`, `<sub>`, `<sup>`, `<o>`, `<a>`, `<span>`
- Any character that's invalid in XML (`&` not starting an entity, `<` not starting a tag, etc.) will cause a parse failure
- **There is no "lenient" mode.** If parsing fails, the entire text is rejected.

### Security considerations

- Pango markup injection could theoretically allow UI spoofing (fake links, misleading formatting)
- No known CVEs specifically for Pango markup injection, but the GNOME security team recommends treating markup strings as privileged
- The `&` character is the most common trigger — it appears in URLs, entity references (`&quot;`, `&#x27;`), and prose

---

## 5. Ranked Comparison Table

| Alternative | Effort | Risk to change | Robustness gain | Maintenance burden | Solves bug class? |
|---|---|---|---|---|---|
| **TextView + TextTag** (Dissent pattern) | High (1-2 weeks) | Medium (UI refactor) | **Total** — no markup string ever parsed | Low — standard GTK API | ✅ Permanently |
| **mistletoe + PangoRenderer** | Medium (3-5 days) | Low (drop-in replacement) | High — proper AST parsing | Medium — maintain custom renderer | ⚠️ Partially |
| **GLib.markup_escape_text + fallback** | Low (1-2 days) | Very Low | Medium — patches current holes | Low | ⚠️ Mostly (with fallback) |
| **WebKitGTK 6.0** | Very High (4-8 weeks) | High (architecture change) | Total — full browser engine | High — WebKit version churn, CSS bridging | ✅ But overkill |
| **PangoCairo render** | Very High (2-4 weeks) | High (custom rendering) | Total — no markup | Very High — custom hit-testing, a11y | ✅ But loses features |
| **md2pango** (port from JS) | Medium (2-3 days) | Low | Low — same approach, slightly better | Medium — maintain a port | ❌ No |
| **Keep current approach** | None | None | None | High — constant firefighting | ❌ No |

---

## 6. Final Recommendation

### If we had 1 week: GLib.markup_escape_text + Defensive Fallback

1. Replace `utils/escaping.py`'s `_strict_unescape` + hand-rolled escaping with `GLib.markup_escape_text()` for all plain-text segments (not the Pango tags themselves — those are app-controlled and safe).
2. Wrap every `label.set_markup()` call in a `safe_set_markup()` helper that catches GMarkup parse errors and falls back to `label.set_text(plain_text)`.
3. Add HTML entity pre-decoding (`&quot;` → `"`, `&#x27;` → `'`) as a pre-processing step before the escaper, since LLMs commonly emit these entities and `GLib.markup_escape_text()` does not decode them.
4. Add a regression test suite with known-problematic strings.

**Result:** No more user-visible warnings. Formatting may degrade to plain text in rare edge cases, but the app never breaks.

### If we had 1 month: mistletoe + TextTag Migration (Hybrid)

1. **Week 1:** Implement the quick fix above as an immediate stopgap.
2. **Week 2-3:** Write a `TextBufferRenderer` for mistletoe that walks the AST and inserts text + TextTags into a `Gtk.TextBuffer`. Port the chat bubble widget from `Gtk.Label` to `Gtk.TextView`.
3. **Week 4:** Migrate the 17 call sites in `chat_render_handler.py` and `chat_bubble.py`. Handle code blocks, links, and streaming delta updates. CSS adjustments.

**Result:** Structurally immune to the markup-parse bug class. Text is selectable. Links work via `activate-link`. Foundation for future features (inline images, spoilers).

### The 9-week web UI migration is justified if:

- You want to render complex content that GTK widgets can't handle (tables, embedded video, LaTeX math, Mermaid diagrams, interactive widgets)
- You're willing to accept 200-300 MB additional memory and WebView startup latency
- You're planning to add a web frontend anyway (e.g., for remote/mobile access)
- The cost of maintaining a custom rich-text renderer in GTK exceeds the cost of delegating to HTML/CSS

If the goal is simply "stop the Pango warnings and have reliable Markdown rendering," the TextView + TextTag approach achieves that in 2-4 weeks without WebKit's overhead.

---

## Appendix A: Key URLs

| Resource | URL |
|---|---|
| Pango Markup docs | https://docs.gtk.org/Pango/pango_markup.html |
| PyGObject TextView tutorial | https://pygobject.gnome.org/tutorials/gtk4/textview.html |
| WebKitGTK API versions | https://blogs.gnome.org/mcatanzaro/2025/04/28/webkitgtk-api-versions/ |
| WebKitGTK 6.0 Python example | https://github.com/HinTak/minimal-web-browsers/blob/main/WebKitGTK4-example.py |
| mistletoe (Markdown parser) | https://github.com/miyuchina/mistletoe |
| mistletoe dev guide (custom renderers) | https://github.com/miyuchina/mistletoe/blob/master/dev-guide.md |
| md2pango (JS/GJS) | https://github.com/ubunatic/md2pango |
| Dissent (GTK4 Discord, Go) | https://github.com/diamondburned/dissent |
| chatkit (Dissent's Markdown rendering) | https://github.com/diamondburned/chatkit/tree/main/md |
| Dino GSoC 2024 (rich text via Pango attrs) | https://wiki.xmpp.org/web/Gsoc2024/Dino/Rich_message_support |
| Jami Pango escaping bug | https://git.jami.net/savoirfairelinux/jami-client-gnome/-/issues/444 |
| Celluloid Pango markup bug | https://github.com/gnome-mpv/gnome-mpv/issues/192 |
| Waybar Pango escaping bug | https://github.com/Alexays/Waybar/issues/240 |
| WebKitGTK memory discussion | https://github.com/webview/webview/issues/421 |
| GLib.markup_escape_text() | https://docs.gtk.org/glib/func.markup_escape_text.html |
| GNOME Discourse: Markdown→Pango converter | https://discourse.gnome.org/t/markdown-to-pango-markup-converter/23123 |

---

## Appendix B: Dissent's TextBlock Architecture (Reference)

The most production-relevant reference for the TextView approach. From `chatkit/md/block/textblock.go`:

```
TextBlock {
    *gtk.TextView      // Wraps a real GTK TextView
    Iter *gtk.TextIter  // Current position in buffer
    Buffer *gtk.TextBuffer
    state *ContainerState  // Parent container with tag table
}
```

Key methods:
- `NewTextBlock(state)` — creates a TextView, TextBuffer, and binds it to a shared TagTable
- `TagBounded(tag, callback)` — runs callback (which inserts text) and applies tag to the inserted range
- `Insert(text)` — inserts plain text at current position (no escaping needed)
- `InsertNewLines(n)` — inserts line breaks
- `ConnectLinkHandler()` — binds the `activate-link` signal for clickable URLs

The TextView is styled via CSS to be transparent, non-editable, cursor-hidden, wrapping:
```css
textview.md-textblock,
textview.md-textblock text {
    background-color: transparent;
    color: @theme_fg_color;
}
```

This is the architecture that CrabCakes should adopt for a permanent fix.
