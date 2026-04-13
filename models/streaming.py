# models/streaming.py — Streaming bubble state
#
# Manifest: reads nothing, writes nothing, no network
# Pure data container for streaming bubble lifecycle state.
# No GTK imports — widget references typed as 'object' for type-checker only.


from dataclasses import dataclass


@dataclass
class StreamingBubble:
    """Tracks state for an in-progress streaming response bubble.

    Stored in ChatRenderHandler._streaming_bubbles dict, keyed by session_key.
    The dataclass replaces a 5-element positional tuple for safe field access.

    Fields:
        container:  The chat box (Gtk.Box or FakeChatBox in tests)
        label:      The Gtk.Label inside the streaming bubble (for text updates)
        role:       "Agent" or "You" — determines bubble alignment
        plain_text: Accumulated plain text from last delta (gateway sends cumulative text)
        bubble:     The streaming bubble widget itself
    """

    container: object    # Gtk.Box or FakeChatBox
    label: object       # Gtk.Label
    role: str           # "Agent" or "You"
    plain_text: str = ""   # default: empty
    bubble: object = None  # default: None
