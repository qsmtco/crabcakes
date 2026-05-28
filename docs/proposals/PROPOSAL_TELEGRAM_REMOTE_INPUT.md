# PROPOSAL: Telegram Bot as Remote Input for CrabCakes

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Proposal — pending Captain approval
**Priority:** Medium
**Effort:** ~3-4 hours

---

## Why

### The Problem
The best speech-to-text on the Captain's iPhone is excellent. But editing transcribed text in Telegram's tiny message box on a phone is painful. The natural workflow is broken:

1. **Speak** → iPhone's excellent STT transcribes perfectly ✅
2. **Edit** → tiny text box, fat fingers, frustrating ❌
3. **Send** → message goes to the right place ✅

Step 2 is the bottleneck. You're fighting a phone keyboard to fix one word in a paragraph.

### The Solution
Use a dedicated Telegram bot as a **remote keyboard** for CrabCakes. Speak on your phone, the transcribed text appears at the cursor position in CrabCakes' input box on your desktop. Review, edit on a real keyboard, hit send.

**Each device does what it's best at:**
- **Phone:** capture speech (iPhone STT is outstanding)
- **Desktop:** edit and review text (real keyboard, big screen)
- **CrabCakes:** send to agents (full project context)

### Why Telegram (not a custom app)
- Telegram's voice-to-text on iPhone leverages the native iOS speech recognizer — it's fast and accurate
- No custom mobile app to build and maintain
- The bot token model is dead simple — CrabCakes polls the bot for messages
- Telegram is already part of the crew's workflow

---

## What

### Before (current)
Type everything on keyboard. Or use CrabCakes' built-in Vosk STT with a microphone.

### After (proposed)
1. Open CrabCakes, navigate to any tab
2. Pick up phone, open Telegram, talk to the CrabCakes input bot
3. Text appears in CrabCakes' input box at the cursor position
4. Review, edit on desktop keyboard, hit send

### How It Works
1. User creates a Telegram bot via @BotFather, gets a bot token
2. User enters the bot token in CrabCakes settings
3. CrabCakes starts a background thread that polls the Telegram Bot API via `getUpdates` (long polling with 25-second timeout)
4. When a message arrives, CrabCakes inserts the text at the cursor position in the active tab's input box
5. User reviews, edits, sends

---

## Technical Design

### Telegram Bot API — Polling vs Webhooks

**Two options exist:**

| | Long Polling (`getUpdates`) | Webhook |
|---|---|---|
| **How it works** | CrabCakes asks Telegram "any new messages?" every 25 seconds | Telegram pushes messages to a URL CrabCakes exposes |
| **Requires** | Outbound HTTPS only | Inbound HTTPS (public URL, SSL cert) |
| **Complexity** | Simple HTTP GET loop | Need a web server, TLS, port forwarding |
| **Latency** | ~0-25 seconds (message arrives immediately if poll is waiting) | Near-instant |
| **Best for** | Desktop apps, low-volume | Cloud servers, high-volume |

**Recommendation: Long Polling.** CrabCakes is a desktop app behind a home network. Setting up a public webhook URL requires port forwarding, dynamic DNS, and TLS certificates. Long polling with a 25-second timeout is zero-config — the bot makes an HTTPS request, Telegram holds the connection open until a message arrives or timeout expires. Messages arrive within seconds. Simple, reliable, no network configuration.

**How long polling works:**
```
CrabCakes thread:  GET https://api.telegram.org/bot<TOKEN>/getUpdates?timeout=25&offset=<last_id>
                    ↓ waits up to 25 seconds...
Telegram:          → returns immediately when message arrives (or after 25s with empty result)
CrabCakes thread:  processes message, inserts text, starts next poll
```

The HTTP connection stays open. Telegram responds the instant a message arrives. It's not "polling every 25 seconds" — it's "connected and waiting." Latency is typically under 1 second.

### Voice Messages vs Text Messages

**Key finding:** The Telegram Bot API does NOT provide automatic transcription of voice messages. When a user sends a voice message, the bot receives a `Voice` object (an audio file), not transcribed text. The transcription API (`messages.transcribeAudio`) is part of the Telegram MTProto client API, not the Bot API.

**Two paths:**

**Path A — Text only (recommended for V1):**
The user speaks into Telegram, iPhone's built-in STT transcribes it, and they send it as a **text message**. This is what happens when you tap the microphone icon on the Telegram keyboard — iPhone STT runs, text appears in the input field, user hits send. The bot receives plain text. Zero additional transcription needed.

**Path B — Voice message transcription (future enhancement):**
If the user sends a raw voice message (holds the mic button and slides up to lock), the bot receives an audio file. CrabCakes would need to download it and transcribe it locally using faster-whisper (already available in the codebase via `utils/stt.py`). This adds complexity — audio download, OGG decode, whisper inference — for marginal benefit since iPhone STT + text send is already excellent.

**Recommendation:** Start with Path A. The iPhone keyboard microphone button gives excellent STT and sends as text. If voice messages are needed later, add whisper transcription as a V2 feature.

### Architecture

```
┌─────────────────┐         ┌──────────────────┐
│   iPhone         │         │   CrabCakes       │
│   Telegram app   │  text   │                   │
│                  │ ──────→ │  Bot Poll Thread  │
│  User speaks →   │         │       ↓           │
│  iPhone STT →    │         │  GLib.idle_add()  │
│  text message →  │         │       ↓           │
│  send to bot     │         │  insert_at_cursor │
│                  │         │       ↓           │
│                  │         │  Input buffer      │
└─────────────────┘         └──────────────────┘
         │                            │
         │    Telegram servers         │
         │    (relay messages)         │
         └────────────────────────────┘
```

**New files:**
- `utils/telegram_input.py` — Telegram Bot API long polling client (pure Python, no GTK)
- Config field in `utils/config.py` — `TELEGRAM_INPUT_BOT_TOKEN`
- UI toggle in settings or toolbar

**Existing code leveraged:**
- `main_content.append_stt_text()` / `buf.insert_at_cursor()` — text insertion at cursor already exists
- `MediaHandler` pattern — same background-thread-to-GTK-via-idle_add pattern
- `GLib.idle_add()` — thread-safe GTK dispatch already used everywhere

**Threading model:**
- One daemon thread for polling
- Thread calls `requests.get()` with 25s timeout (blocks until message or timeout)
- On message: `GLib.idle_add(callback, text)` to insert into input buffer
- Thread checks `self._running` flag on each loop iteration for clean shutdown

### Security

- Bot token stored in config (same pattern as API keys)
- Only messages from the configured user's chat_id are processed (reject all others)
- Bot doesn't send any messages back — it's receive-only (input device)
- No web server, no open ports, no public URLs
- All communication over HTTPS to Telegram's API

---

## Scope

| In Scope | Out of Scope |
|----------|-------------|
| Bot token config field | Voice message transcription (V2) |
| Background polling thread | Custom mobile app |
| Text insertion at cursor | Bot sending replies back to Telegram |
| Only active tab's input box | Multi-user support |
| Only when CrabCakes is open | Queuing messages when CrabCakes is closed |
| Text messages only (not voice files) | Integration with OpenClaw gateway |

---

## File Change Summary

| File | Change | Lines | Risk |
|------|--------|-------|------|
| `utils/telegram_input.py` | NEW — Bot API client, long polling, message parsing | ~80 | Medium — new file, networking |
| `utils/config.py` | Add `TELEGRAM_INPUT_BOT_TOKEN` + enable flag | ~5 | Low |
| `ui/handlers/media_handler.py` | Wire telegram input start/stop | ~15 | Low |
| `ui/window.py` | Init telegram input on startup, pass main_content | ~10 | Low |
| `ui/views/main_content.py` | No changes — `append_stt_text()` already works | 0 | — |
| `docs/ARCHITECTURE.md` | New section for Telegram input | ~20 | Low |
| **Total** | | **~130 lines** | |

---

## Acceptance Criteria

- [ ] User can enter a Telegram bot token in CrabCakes config
- [ ] CrabCakes starts polling the bot on startup when token is configured
- [ ] Text messages sent to the bot appear in CrabCakes' input box at cursor position
- [ ] Messages from other users are ignored (only configured chat_id)
- [ ] Polling stops cleanly when CrabCakes closes (daemon thread + running flag)
- [ ] No impact on CrabCakes UI responsiveness (network on background thread)
- [ ] Text insertion preserves existing input (appends at cursor, doesn't overwrite)
- [ ] Works on the currently active tab regardless of which tab it is

---

## Future Enhancements (Not In Scope)

1. **Voice message transcription** — Download OGG audio from Telegram, transcribe with faster-whisper, insert text. CrabCakes already has the whisper infrastructure.
2. **Bot replies** — Allow the bot to send confirmation back to Telegram ("Message received ✓").
3. **Session routing** — `/ask @Coder` in Telegram routes to a specific agent tab.
4. **Message queuing** — Store messages when CrabCakes is closed, replay on open.

---

## Why Now

- The architecture is already in place (`append_stt_text`, `insert_at_cursor`, `GLib.idle_add` pattern)
- Telegram Bot API is stable, well-documented, and requires zero infrastructure
- The feature is small (~130 lines) but solves a real daily workflow friction
- iPhone STT quality makes this actually useful — it's not a gimmick
