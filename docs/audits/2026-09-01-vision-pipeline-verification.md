# Crabcakes Multimodal / Vision Pipeline Verification

**Date:** 2026-09-01
**Scope:** Read-only verification of a third-party claim that Crabcakes' vision failure is a harness/pipeline limitation, not a model limitation
**Files modified:** none

---

## Claim Under Test

> "The model is vision-capable, but CrabCakes never puts image data in the messages it sends, so the model genuinely can't see anything and correctly reports it has no vision."

## Verdict

**Mostly correct, with one nuance worth noting.** The diagnosis — harness limitation, not model limitation — is accurate. All 5 evidence points check out, but the claim that there is "zero handling for images anywhere" missed that the **UI has display-only image support**, which actually strengthens the diagnosis.

---

## Confirmed ✅

### 1. No image content blocks reach the LLM

Zero hits for `image_url` / base64-image / `media_type` content construction anywhere in `agent/`, `gateway/`, or `chat/`. The only base64 uses in `gateway/client.py` (lines 199, 540) are Ed25519 key signing, as claimed — unrelated to images.

### 2. The runtime message model is string-only

`models/conversation.py:122` — `content: str`. `add_user_message(content: str)` as well. There is structurally no way to put an image block in a conversation message.

### 3. `convert.py` handles text + tool_use blocks only

`agent/llm/convert.py` — no `{"type": "image", "source": ...}` path for Anthropic, no multimodal user content for OpenAI. Passes string content through untouched.

### 4. `web_fetch` rejects non-text

`agent/tools.py:806-808`: returns an error for any content-type that is not `text/html` or `text/plain`. Confirmed verbatim.

### 5. No vision capability claims in `prompts/`

No "you can see images" statements anywhere in the system prompts.

---

## Nuance the claim missed ⚠️

**Image *display* support exists in the UI** — it's just display-only:

- `chat_handler.py:655-661` recognizes `input_image` blocks with `image_url` **from gateway media attachments** and converts them to ` ```image ` code blocks
- `chat_bubble.py` renders those as clickable images; `activity_handler.py:156` counts them in token estimates; `styles.py` has `.chat-image` CSS

So the picture is: the gateway *can* deliver image attachments, Crabcakes can *render* them to the user, but the ingestion → conversation → provider path silently flattens/discards them because `Message.content` is a `str`. The model never receives them — consistent with it "correctly reporting it has no vision."

---

## Fix path (agreed, with one addition)

The original fix proposal is right:

1. Image attachment ingestion → store as base64
2. Emit multimodal content blocks (`image_url` for OpenAI-format; `{"type": "image", "source": {...}}` for Anthropic in `convert.py`)
3. Relax the text-only guard in `tools.py` or add a `read_image` tool

**Addition:** since `chat_handler` already parses gateway `input_image` blocks, the natural ingestion hook is *there* — store the image_url/base64 alongside the message (e.g., `content: str | list[dict]`) rather than building attachment handling from scratch.
