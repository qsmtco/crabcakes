# SPEC: Telegram Bot as Remote Input for CrabCakes

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL_TELEGRAM_REMOTE_INPUT.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md §3.16, §3.16): `utils/telegram_input.py` is a pure Python utility with no GTK imports — follows the `utils/stt.py` pattern. Background thread dispatches GTK calls via `GLib.idle_add()`. Config stored in `~/.config/crabcakes/config.json` following `utils/improve.py` pattern. `MediaHandler` owns the wiring between utility and UI, following existing STT pattern.

---

## DISCOVERY

- **Read `utils/stt.py`:** `STTEngine` class. Background thread for capture, `GLib.idle_add()` for callback dispatch. Daemon thread. Pattern: `start()` → record → `stop_async(on_done=callback)` → worker thread → `GLib.idle_add(callback, text)`. This is the exact threading model to follow.
- **Read `utils/improve.py`:** Config loading from `get_config_file()` → `~/.config/crabcakes/config.json`. Cached via `_config` global with `_config_lock`. Reads `apiKey` field. This is the config pattern to follow.
- **Read `utils/config.py`:** `get_config_file()` returns `~/.config/crabcakes/config.json`. `COMMAND_PREFIX` at line 71. No existing Telegram config fields.
- **Read `ui/handlers/media_handler.py`:** `MediaHandler.__init__(main_content, improve_module, GLib_module)`. Stores `self._mc = main_content` for direct access. `self._GLib = GLib_module` for `idle_add`. `_append_and_send()` calls `self._mc.append_stt_text(text)`. This is the handler pattern to follow.
- **Read `ui/views/main_content.py`:** `append_stt_text(text)` at line 773 — calls `buf.insert_at_cursor(text)` then `self.user_input.grab_focus()`. `user_input` property at line 28 returns `self._user_input` (Gtk.TextView). This is the insertion point — already exists, no changes needed.
- **Read `ui/window.py`:** `MediaHandler` created at line 211 with `main_content`, `improve_module`, `GLib_module`. Wired at line 425. This is where Telegram input gets wired.
- **Read `docs/ARCHITECTURE.md`:** §3.16 describes MediaHandler — "all media I/O" including STT. Telegram input fits naturally under MediaHandler. §3.16 threading: "All GTK calls go through `GLib.idle_add()`". File tree line 99: `media_handler.py # MediaHandler — STT + improve`.
- **Telegram Bot API research:** Two update methods — `getUpdates` (long polling) and `setWebhook` (push). Long polling with `timeout=25` holds connection open, responds instantly on message. No public URL needed. Bot receives text messages as `Message.text`. Voice messages as `Message.voice` (audio file) — transcription requires separate processing. For V1: text messages only.
- **Python `requests` library:** Available on the system. Used for HTTP GET to `https://api.telegram.org/bot<TOKEN>/getUpdates`.
- **Config pattern:** `~/.config/crabcakes/config.json` already stores `apiKey`. Add `telegramInputBotToken` and `telegramInputChatId` to same file.

---

## 1. Overview

### Problem
The Captain wants to use iPhone's excellent speech-to-text to dictate messages, but editing transcribed text in Telegram's tiny mobile input is frustrating. The natural workflow — speak on phone, edit on desktop — is broken.

### Solution
CrabCakes runs a Telegram Bot API long polling client in a background thread. Text messages sent to the bot are inserted at the cursor position in CrabCakes' active input box. The user reviews, edits, and sends from the desktop.

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| New `utils/telegram_input.py` — Bot API long polling client | Voice message transcription (V2) |
| Config fields in `config.json` | Bot sending replies to Telegram |
| Wiring in `MediaHandler` | Multi-user / chat_id filtering (V2) |
| `GLib.idle_add` dispatch to input box | OpenClaw gateway integration |
| Text messages only | Message queuing when CrabCakes closed |

---

## 2. Changes by File

### 2.1 `utils/telegram_input.py` — NEW FILE

**Architecture:** Pure Python utility, no GTK imports. Follows `utils/stt.py` pattern — background daemon thread, callback-based, clean start/stop lifecycle.

**Public API:**

```python
class TelegramInput:
    """Telegram Bot API long polling client — receives text messages and 
    inserts them into CrabCakes' input box.
    
    Lifecycle:
        ti = TelegramInput(bot_token, on_text=callback)
        ti.start()    → begin polling in background thread
        ti.stop()     → clean shutdown
    
    Threading: daemon thread, GTK dispatch via GLib.idle_add in callback.
    """
```

**Constructor:**

```python
def __init__(self, bot_token: str, on_text: Callable[[str], None]):
    """
    Args:
        bot_token: Telegram bot token from @BotFather (e.g. "123456:ABC-DEF...")
        on_text:   Callback(text: str) — called on each text message.
                   Called from background thread — use GLib.idle_add in callback.
    """
    self._bot_token = bot_token
    self._on_text = on_text
    self._running = False
    self._thread: threading.Thread | None = None
    self._last_update_id = 0  # track processed updates for offset
```

**Methods:**

```python
def start(self) -> None:
    """Start polling in a background daemon thread."""
    if self._running:
        return
    self._running = True
    self._thread = threading.Thread(target=self._poll_loop, daemon=True)
    self._thread.start()

def stop(self) -> None:
    """Signal shutdown and wait for thread to finish."""
    self._running = False
    if self._thread is not None:
        self._thread.join(timeout=5)

@property
def is_running(self) -> bool:
    return self._running
```

**Poll loop:**

```python
def _poll_loop(self) -> None:
    """Background thread: long poll Telegram Bot API for updates."""
    api_url = f"https://api.telegram.org/bot{self._bot_token}"
    
    while self._running:
        try:
            resp = requests.get(
                f"{api_url}/getUpdates",
                params={
                    "timeout": 25,        # long poll — holds connection open
                    "offset": self._last_update_id + 1,  # acknowledge processed updates
                    "allowed_updates": '["message"]',     # only receive messages
                },
                timeout=30,  # HTTP timeout slightly longer than polling timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("ok"):
                logger.warning("[telegram-input] API error: %s", data.get("description"))
                continue
            
            for update in data.get("result", []):
                self._process_update(update)
                
        except requests.exceptions.Timeout:
            # Normal — long poll timeout expired, retry
            continue
        except requests.exceptions.ConnectionError:
            logger.warning("[telegram-input] connection error, retrying in 5s")
            time.sleep(5)
        except Exception as e:
            logger.error("[telegram-input] unexpected error: %s", e)
            time.sleep(5)
```

**Update processing:**

```python
def _process_update(self, update: dict) -> None:
    """Extract text from a Telegram update and call the callback."""
    self._last_update_id = update.get("update_id", 0)
    
    message = update.get("message")
    if not message:
        return
    
    # Only process text messages (not voice, photos, etc.)
    text = message.get("text", "").strip()
    if not text:
        return
    
    # Skip bot commands (/start, /help, etc.)
    entities = message.get("entities", [])
    for entity in entities:
        if entity.get("type") == "bot_command" and entity.get("offset") == 0:
            return
    
    if self._on_text:
        self._on_text(text)
```

**Imports:**

```python
import logging
import time
import threading
from typing import Callable

import requests

logger = logging.getLogger(__name__)
```

**Line count estimate:** ~100 lines.

**Exception types:**
- `requests.exceptions.Timeout` — normal, long poll expired. Continue loop.
- `requests.exceptions.ConnectionError` — network issue. Sleep 5s, retry.
- `requests.exceptions.HTTPError` — bad token, rate limited, etc. Logged, retry.
- `json.JSONDecodeError` — malformed response. Logged, retry.
- `Exception` — catch-all. Logged, sleep 5s, retry. Never crashes the thread.

**Why `requests` (not `urllib`):** `requests` is already available on the system. Simpler timeout handling, automatic JSON parsing, cleaner error hierarchy. `urllib` would work but adds complexity for no benefit.

**Why `allowed_updates: '["message"]'`:** Tells Telegram to only send message updates, not channel posts, edited messages, etc. Reduces noise.

**Why offset tracking:** Telegram stores updates for 24h. The `offset` parameter tells Telegram "I've processed everything up to this ID, don't send them again." Without it, every restart would replay all messages from the last 24 hours.

---

### 2.2 `ui/handlers/media_handler.py`

**What changes:**
1. Import `TelegramInput` from `utils.telegram_input`
2. Add `self._telegram_input` instance variable
3. Add `start_telegram_input()` / `stop_telegram_input()` methods
4. In `__init__`, attempt auto-start if config has bot token

**Code — new import (top of file):**

```python
from utils.telegram_input import TelegramInput
```

**Code — new instance variable in `__init__`:**

After `self._stt_engine = self._stt_class(on_result=self._on_result)`:

```python
        self._telegram_input: TelegramInput | None = None  # Telegram bot remote input
```

**Code — new methods:**

```python
    # ── Telegram Remote Input ─────────────────────────────────────────────

    def start_telegram_input(self, bot_token: str) -> None:
        """Start polling a Telegram bot for text messages to insert into input."""
        if self._telegram_input is not None:
            self.stop_telegram_input()
        
        self._telegram_input = TelegramInput(
            bot_token=bot_token,
            on_text=self._on_telegram_text,
        )
        self._telegram_input.start()

    def stop_telegram_input(self) -> None:
        """Stop the Telegram input polling thread."""
        if self._telegram_input is not None:
            self._telegram_input.stop()
            self._telegram_input = None

    def _on_telegram_text(self, text: str) -> None:
        """Handle text from Telegram — insert at cursor position.
        
        Called from the polling background thread.
        Dispatches to GTK main thread via GLib.idle_add.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._insert_telegram_text, text)
        else:
            self._insert_telegram_text(text)

    def _insert_telegram_text(self, text: str) -> None:
        """Insert Telegram text at cursor — runs on GTK main thread."""
        self._mc.append_stt_text(text)
```

**Verified against source:** `self._mc` is `main_content` (line 23 of media_handler.py). `self._GLib` is `GLib_module` (line 25). `self._mc.append_stt_text(text)` calls `buf.insert_at_cursor(text)` at line 779 of main_content.py. This is the exact same dispatch pattern as `_on_result()` (line 54-57).

**Why `append_stt_text` and not a new method:** The existing `append_stt_text()` does exactly what we need — `buf.insert_at_cursor(text)` + `grab_focus()`. It inserts at cursor, doesn't overwrite. No new method needed.

**Line count estimate:** ~30 lines added.

---

### 2.3 `ui/window.py`

**What changes:**
1. Auto-start Telegram input on build if config has bot token

**Code — after MediaHandler creation (after line 215):**

```python
        # Auto-start Telegram remote input if bot token is configured
        self._start_telegram_input_if_configured()
```

**Code — new method:**

```python
    def _start_telegram_input_if_configured(self) -> None:
        """Check config for Telegram bot token and start polling if found."""
        import json
        from utils.config import get_config_file
        
        try:
            with open(get_config_file()) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        
        token = cfg.get("telegramInputBotToken", "").strip()
        if token:
            self._media_handler.start_telegram_input(token)
```

**Code — clean shutdown in destroy handler:**

Find the existing destroy/window close handler and add:

```python
        # Stop Telegram input polling
        if self._media_handler:
            self._media_handler.stop_telegram_input()
```

**Line count estimate:** ~20 lines added.

---

### 2.4 `utils/config.py`

**No code changes.** Config fields (`telegramInputBotToken`, `telegramInputChatId`) live in `config.json`, not in `utils/config.py`. The config.py module only provides path resolution (`get_config_file()`). This follows the existing pattern — `apiKey` for MiniMax is stored in `config.json` and read directly by `utils/improve.py`, not via a config.py constant.

---

### 2.5 `ui/views/main_content.py`

**No changes.** `append_stt_text()` at line 773 already does `buf.insert_at_cursor(text)` + `grab_focus()`. Exactly what we need.

---

### 2.6 `docs/ARCHITECTURE.md`

**Updates required:**

1. §3.16 `ui/handlers/media_handler.py` description: add "Telegram remote input" to responsibilities
2. File tree line 99: update comment to `# MediaHandler — STT + improve + Telegram input`
3. File tree: add `telegram_input.py` to `utils/` section
4. §3.16 new subsection for `utils/telegram_input.py`

**New section:**

```markdown
### 3.XX `utils/telegram_input.py` — Telegram Bot Remote Input

**Responsibility:** Long-poll a Telegram bot for text messages and deliver them to CrabCakes' input box. Pure Python, no GTK.

**Public API:**
```python
from utils.telegram_input import TelegramInput

ti = TelegramInput(bot_token="...", on_text=callback)
ti.start()    # daemon thread starts polling
ti.stop()     # clean shutdown
```

**Thread safety:** `on_text` callback fires from the polling thread. Handler dispatches to GTK via `GLib.idle_add()`.

**Config:** Bot token stored in `~/.config/crabcakes/config.json` as `telegramInputBotToken`.
```

**Line count estimate:** ~20 lines added.

---

## 3. Data Flow

### User sends text message to Telegram bot:
1. User opens Telegram on iPhone, navigates to the CrabCakes input bot
2. User taps microphone on keyboard → iPhone STT transcribes → text appears in input field
3. User taps send → text message goes to Telegram servers
4. CrabCakes background thread: `requests.get("/getUpdates?timeout=25")` → Telegram responds immediately with the message
5. `_process_update()` extracts `text` from the `message` object
6. `_on_text(text)` called from background thread
7. `GLib.idle_add(self._insert_telegram_text, text)` dispatches to GTK main thread
8. `_insert_telegram_text()` calls `self._mc.append_stt_text(text)`
9. `main_content.append_stt_text()` calls `buf.insert_at_cursor(text)` + `grab_focus()`
10. Text appears in the active tab's input box at cursor position
11. User reviews, edits on desktop keyboard, hits send

### Startup:
1. `window._build()` creates `MediaHandler`
2. `window._start_telegram_input_if_configured()` reads `config.json`
3. If `telegramInputBotToken` present → `media_handler.start_telegram_input(token)`
4. `TelegramInput.__init__()` stores token and callback
5. `TelegramInput.start()` spawns daemon thread → `_poll_loop()` begins
6. First `getUpdates` call with `offset=0` → fetches any pending updates

### Shutdown:
1. Window destroy handler calls `media_handler.stop_telegram_input()`
2. `TelegramInput.stop()` sets `self._running = False` → `thread.join(timeout=5)`
3. Current `requests.get()` either returns (timeout) or is interrupted by thread termination
4. Thread exits cleanly

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `utils/telegram_input.py` | **NEW** | ~100 | Medium — networking, threading |
| `ui/handlers/media_handler.py` | Modified | ~30 | Low — follows existing STT pattern |
| `ui/window.py` | Modified | ~20 | Low — startup + shutdown wiring |
| `utils/config.py` | No change | 0 | — |
| `ui/views/main_content.py` | No change | 0 | — |
| `docs/ARCHITECTURE.md` | Modified | ~20 | Low — docs only |
| **Total** | | **~170 lines** | |

**Files NOT changed (already correct):**
- `utils/config.py` — provides `get_config_file()` path, no new constants needed
- `ui/views/main_content.py` — `append_stt_text()` already does `insert_at_cursor` + `grab_focus`
- `utils/stt.py` — existing STT, no changes needed
- `utils/improve.py` — config loading pattern to follow, no changes

---

## 5. Implementation Order

1. **Create `utils/telegram_input.py`** — `TelegramInput` class with poll loop, update processing, start/stop
2. **Test standalone** — `python3 -c "from utils.telegram_input import TelegramInput; print('import OK')"`
3. **Add wiring to `media_handler.py`** — import, instance variable, start/stop/insert methods
4. **Add startup/shutdown to `window.py`** — config read, auto-start, clean shutdown
5. **Manual test** — create a bot via @BotFather, add token to config.json, start CrabCakes, send text from Telegram
6. **Update `docs/ARCHITECTURE.md`** — new section for telegram_input.py, update media_handler description
7. **Commit and push**

**Verification at each step:**
1. `python3 -c "from utils.telegram_input import TelegramInput"` → import OK
2. Create bot, get token → `python3 -c "from utils.telegram_input import TelegramInput; ti = TelegramInput('TOKEN', print); ti.start(); import time; time.sleep(30); ti.stop()"` → sends test message from Telegram, sees it printed
3. Start CrabCakes → text from Telegram appears in input box at cursor
4. Close CrabCakes → thread stops cleanly, no hanging

---

## 6. Acceptance Criteria

- [ ] `utils/telegram_input.py` exists, no GTK imports, pure Python
- [ ] `TelegramInput.start()` spawns daemon thread that polls Telegram API
- [ ] Long polling with 25s timeout — connection held open, instant response on message
- [ ] Text messages from Telegram inserted at cursor position in active tab
- [ ] Existing text in input box preserved (insert_at_cursor, not overwrite)
- [ ] Bot commands (/start, /help) ignored — only plain text processed
- [ ] Offset tracking prevents re-processing old messages on restart
- [ ] Config stored in `~/.config/crabcakes/config.json` as `telegramInputBotToken`
- [ ] Auto-starts on CrabCakes launch when token is configured
- [ ] Clean shutdown — thread stops within 5 seconds on window close
- [ ] No impact on UI responsiveness (all network on background thread)
- [ ] All GTK calls go through `GLib.idle_add()` (architecture rule)
- [ ] Follows `utils/stt.py` threading pattern
- [ ] Follows `utils/improve.py` config loading pattern

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| No bot token in config | No polling started, CrabCakes works normally |
| Invalid bot token | `getUpdates` returns 401 → logged, retries every 5s |
| Network outage | `ConnectionError` → logged, retries every 5s |
| User sends voice message (not text) | `message.text` is empty → skipped |
| User sends photo | `message.text` is empty → skipped |
| User sends /start or /help | Bot command entity at offset 0 → skipped |
| Multiple messages in one poll response | All processed in order, offset updated to last |
| CrabCakes closed while poll is waiting | `self._running = False`, `thread.join(5)`, thread exits on next response or timeout |
| Empty text message | `text.strip()` is empty → skipped |
| Very long message (>4096 chars) | Telegram limit is 4096, so this can't happen |
| Bot token belongs to wrong bot | Polls wrong bot — no messages received. User fixes token in config. |
| Multiple users message the bot | All messages processed (V1 has no chat_id filter) |

---

## 8. ARCHITECTURE.md Updates Required

- §3.16 description: add "Telegram remote input" to MediaHandler responsibilities
- File tree line 99: update comment
- File tree utils section: add `telegram_input.py`
- New subsection for `utils/telegram_input.py` with public API and threading model

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `MediaHandler.__init__` signature: `__init__(self, main_content, improve_module=None, GLib_module=None, stt_engine_class=None)` — verified at line 14 ✅
   - `self._mc` is `main_content` — verified at line 23 ✅
   - `self._GLib` is `GLib_module` — verified at line 25 ✅
   - `self._mc.append_stt_text(text)` exists at main_content.py line 773 ✅
   - `buf.insert_at_cursor(text)` at main_content.py line 779 ✅
   - `get_config_file()` returns `~/.config/crabcakes/config.json` — verified in config.py line 28 ✅
   - `MediaHandler` created at window.py line 211 ✅
   - `requests` library available — verified ✅

2. **Did I catch all exception types?**
   - `requests.exceptions.Timeout` — long poll timeout (normal) ✅
   - `requests.exceptions.ConnectionError` — network down ✅
   - `requests.exceptions.HTTPError` — bad token, rate limit ✅
   - `json.JSONDecodeError` — malformed response ✅
   - `Exception` — catch-all, never crashes thread ✅
   - `FileNotFoundError`, `json.JSONDecodeError` in config loading ✅

3. **Did I verify key structures?**
   - Telegram `getUpdates` response: `{"ok": true, "result": [{"update_id": 123, "message": {"text": "..."}}]}` — verified against Bot API docs ✅
   - `config.json` is `{"apiKey": "...", "telegramInputBotToken": "..."}` — follows existing pattern ✅
   - `append_stt_text` takes `str`, dispatches to `insert_at_cursor` — verified ✅

4. **Did I trace the data flow end-to-end?**
   - iPhone → Telegram → Bot API → `requests.get()` → `_process_update()` → `_on_text()` → `GLib.idle_add()` → `_insert_telegram_text()` → `append_stt_text()` → `buf.insert_at_cursor()`. Full path traced ✅

5. **Would an implementer produce working code?**
   - Yes. All method signatures, threading patterns, config locations, and dispatch mechanisms verified against source. No invented APIs.

6. **Architecture compliance verified?**
   - `utils/telegram_input.py`: no GTK imports, pure Python, daemon thread ✅
   - `MediaHandler`: dispatches GTK calls via `GLib.idle_add()` ✅
   - Config: follows `improve.py` pattern, reads `config.json` ✅
   - No new CSS classes needed ✅
   - No cross-layer violations ✅
