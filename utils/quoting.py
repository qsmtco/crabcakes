# utils/quoting.py
# Quoted-payload parsing — pure Python, no GTK, no network.
#
# Shared by command_handler.py and agent_command_handler.py per
# A2A_QUOTED_PAYLOAD_SPEC §5.1.
#
# Public API:
#   _parse_quoted_payload(text: str, start: int) -> tuple[str | None, int]

# Payload size limit per A2A quoted payload spec §4.5
_PAYLOAD_MAX_CHARS = 4096


def _parse_quoted_payload(text: str, start: int) -> tuple[str | None, int]:
    """Parse a quoted payload starting at position `start`.

    Expects text[start] == '"'. Reads to the matching '"', respecting
    escape sequences (backslash-quote \" and double-backslash \\).

    Algorithm:
      1. If text[start] != '"', return (None, start) immediately.
      2. Scan forward from start+1.
      3. On end-of-string without closing '"': return (None, start) — caller
         distinguishes user-agent context (→ error) vs. agent context (auto-close).
      4. On '\\"': append literal '"', advance 2.
      5. On '\\\\': append literal '\\', advance 2.
      6. On '"': close — reject empty payload per spec §4.5 → return (None, start).
      7. On any other char: append, advance 1.

    Args:
        text:  Full input string.
        start: Position of the opening '"' in text.

    Returns:
        (payload_string, position_after_close_quote) on success.
        (None, start) if text[start] != '"', no closing '"' found, or payload is empty.

    Examples:
        _parse_quoted_payload('"hello"', 0)             → ('hello', 7)
        _parse_quoted_payload('"she said \\"hi\\""', 0) → ('she said "hi"', 17)
        _parse_quoted_payload('"hello\\\\world"', 0)    → ('hello\\world', 16)
        _parse_quoted_payload('"unclosed', 0)           → (None, 0)
        _parse_quoted_payload('""', 0)                  → (None, 0)  # empty = reject
    """
    if start >= len(text) or text[start] != '"':
        return (None, start)

    payload_parts: list[str] = []
    i = start + 1
    n = len(text)

    while i < n:
        ch = text[i]
        if ch == '\\' and i + 1 < n:
            next_ch = text[i + 1]
            if next_ch == '"':
                payload_parts.append('"')
                i += 2
                continue
            elif next_ch == '\\':
                payload_parts.append('\\')
                i += 2
                continue
            # Any other backslash: treat as literal backslash (spec §4.7)
            payload_parts.append('\\')
            i += 1
            continue
        elif ch == '"':
            # Closing quote found — reject empty payload per spec §4.5
            payload = ''.join(payload_parts)
            if not payload:
                return (None, start)
            return (payload, i + 1)
        else:
            payload_parts.append(ch)
            i += 1

    # End of string without closing quote
    return (None, start)