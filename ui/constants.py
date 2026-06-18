# ui/constants.py
# Cross-cutting UI constants used by both views and handlers.
#
# Architecture rule (ARCHITECTURE.md §8.6 R7):
#   Views must not import from ui/handlers/. To share state between a view
#   and a handler, put the constant here. Both sides import from this neutral
#   module.
#
# Mutable state lives here, not on handler classes, when both the view and
#   the handler need to read AND write it. For one-way state (handler-only or
#   view-only), pass via constructor or setter from ui/window.py instead.

# Streaming toggle: when True, the chat shows live token deltas as the agent
# types. When False, only the final assembled message is shown. The toolbar's
# stream button toggles this; ChatHandler reads it on every streaming event.
STREAMING_ENABLED: bool = False
