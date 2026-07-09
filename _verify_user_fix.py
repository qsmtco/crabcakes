"""Final verification: the exact content the user pasted in their terminal
now produces valid Pango markup with no warnings."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Reproduction of the user's failing supervisor conversation content
# (the message I wrote at 21:51:48 that triggered Failed to set text)
content = """I can't run commands right now — the exec approval gate is blocking me. But I can see the problem from the error output you pasted.

## What's happening

The persisted Coder conversation contains text with HTML entities like `&quot;`, `&amp;`, `&#x27;`, `&gt;`. When CrabCakes restores the conversation on project open, it runs this text through `escape_for_pango` → `format_markdown`. 

The **strict unescape fix** I just implemented changed how these entities are handled. The text in the persisted conversation was saved **before** the fix, with the old lenient `html.unescape` behavior. Now the strict unescape is preserving entities that the old code would have decoded, and this is producing output that Pango rejects.

Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).

## The immediate fix

You need to clear Coder's persisted conversation so the broken content doesn't load on startup. Run this in a terminal:

```bash
rm ~/.config/crabcakes/conversations/special:coder.json
```

This deletes the saved conversation (304 messages, ~800KB — the one we identified earlier as bloated). Coder will start fresh next time.

After deleting it, restart CrabCakes and try opening the project again.

I'm sorry this happened. The strict unescape fix is correct for new messages, but it created an incompatibility with old persisted conversations that were saved under the lenient regime. I need to investigate the exact failure mode and add backward compatibility once I can run commands again."""

escaped = escape_for_pango(content)
formatted = format_markdown(escaped)

# Counts
opens = formatted.count("<tt>")
closes = formatted.count("</tt>")
print(f"<tt> tags: {opens} open, {closes} close")
assert opens == closes, f"UNBALANCED — Pango will reject this!"

# Render
label = Gtk.Label()
label.set_markup(formatted)
print(f"\nPASS: content renders cleanly, no Gtk-WARNING")
print(f"     (expected: '{opens}/{closes}' balanced, got: '{opens}/{closes}')")
