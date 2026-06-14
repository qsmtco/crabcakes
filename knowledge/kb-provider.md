# KB Provider System

This guide covers the CrabCakes local knowledge base (KB) provider — how it works, how it fits into the provider system, and how to configure and troubleshoot it.

---

## Architecture Overview

The KB provider system has three layers:

1. **KB Lookup** (`agent/kb_lookup.py`) — Cosine-similarity retrieval over indexed documentation chunks using sentence-transformer embeddings
2. **KB Server** (`agent/kb_server.py`) — HTTP server wrapping the lookup in an OpenAI-compatible API on `localhost:18790`
3. **Provider Integration** — Registered as `local-kb` in `providers.yaml`, used by the agent runtime like any other LLM provider

### How They Fit Together

```
User asks Auxilium a question
        │
        ▼
AgentRuntime._call_llm()
        │
        ▼
local-kb provider → HTTP POST to localhost:18790/v1/chat/completions
        │
        ▼
kb_server extracts the user message
        │
        ▼
kb_lookup embeds the question (BAAI/bge-small-en-v1.5)
        │
        ▼
Cosine similarity against indexed chunks
        │
    ┌───┴───┐
    │       │
score     score
≥ 0.55    < 0.55
    │       │
    ▼       ▼
Return    Return
chunks    [KB_OUT_OF_SCOPE]
```

The agent runtime treats the KB server exactly like any other OpenAI-compatible API. Zero runtime changes are needed — the KB server is just another provider endpoint.

---

## KB Server (`agent/kb_server.py`)

### What It Does

The KB server is a lightweight HTTP server built with Python stdlib (`http.server`, `threading`). It:

- Binds to **127.0.0.1 only** (no external access)
- Listens on port **18790**
- Handles `POST /v1/chat/completions` (OpenAI-compatible)
- Handles `GET /health` (health check)
- Returns 404 for all other paths, 405 for PUT/DELETE/PATCH

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `KB_SERVER_PORT` | 18790 | Default listen port |
| `KB_OUT_OF_SCOPE` | `[KB_OUT_OF_SCOPE]` | Sentinel returned when KB cannot answer |
| `_KB_MIN_SCORE` | 0.35 | Minimum cosine similarity for chunk inclusion |
| `_KB_TOP_K` | 5 | Maximum chunks returned |
| `_KB_CONFIDENCE_THRESHOLD` | 0.55 | Top-score threshold for answering vs. out-of-scope |

### Request Flow

1. Extract the last user message from the `messages` array
2. Call `kb_lookup(question, top_k=5, min_score=0.35)`
3. If no chunks returned → return `[KB_OUT_OF_SCOPE]`
4. If top chunk score < 0.55 → return `[KB_OUT_OF_SCOPE]`
5. Otherwise → format chunks into a response string and return

The confidence threshold (0.55) is intentionally higher than the min_score (0.35). This two-tier system filters weak false-positive matches that pass the inclusion threshold but aren't actually relevant.

### Response Format

**Successful response** (OpenAI-compatible):

```json
{
  "id": "chatcmpl-kb-<8-char-hex>",
  "object": "chat.completion",
  "model": "local-kb",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Based on the CrabCakes knowledge base:\n\n---\n**Source:** knowledge/setup.md :: Installing on Linux\n\n<chunk text>\n"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0}
}
```

**Out-of-scope response**: Same format but `content` is `[KB_OUT_OF_SCOPE]`.

**Note:** Usage tokens are always 0 — the KB server does not track token counts since it doesn't use an LLM.

### Server Lifecycle

- **Started** in `AgentRuntimeHandler.__init__()` after `ensure_kb_provider()` succeeds
- **Stopped** in `AgentRuntimeHandler.stop_all()` (called on window shutdown)
- Uses `server.shutdown()` + `server.server_close()` for clean shutdown
- Runs as a daemon thread (`kb-server-18790`)

### Public API

```python
from agent.kb_server import (
    start_kb_server,      # Start server on port 18790 (idempotent)
    stop_kb_server,       # Stop server (idempotent)
    is_kb_server_running,  # Check if running
    KB_SERVER_PORT,       # 18790
    KB_OUT_OF_SCOPE,      # "[KB_OUT_OF_SCOPE]"
)
```

---

## KB Lookup (`agent/kb_lookup.py`)

### What It Does

Performs semantic retrieval over pre-indexed documentation chunks:

1. Lazy-loads the `BAAI/bge-small-en-v1.5` sentence-transformers model (384-dim, ~130MB, MIT-licensed)
2. L2-normalizes the question embedding
3. Computes cosine similarity via dot product against pre-normalized chunk embeddings
4. Returns top-K chunks above `min_score`, sorted by score descending

### Index Format

The index is produced by `scripts/rebuild_kb_index.py` and stored at:

```
knowledge/.index/chunks.json     — list of {id, source, section, text}
knowledge/.index/embeddings.npy  — float32 array, shape (N, 384), L2-normalized
```

Chunks are split by `##` level-2 headings in each `.md` file.

### KBChunk Dataclass

```python
@dataclass
class KBChunk:
    id: str          # chunk identifier
    source: str      # e.g. "knowledge/setup.md"
    section: str     # e.g. "Installing on Linux"
    text: str        # the chunk content
    score: float     # cosine similarity, 0..1
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `top_k` | 3 | Maximum chunks to return (KB server uses 5) |
| `min_score` | 0.3 | Minimum cosine similarity (KB server uses 0.35) |
| `model_name` | `BAAI/bge-small-en-v1.5` | Embedding model |

### Fail-Soft Design

`kb_lookup()` is designed to never raise — it always returns a list (possibly empty):

- Missing index → `[]`
- Missing `sentence_transformers` → `[]`
- No chunk above threshold → `[]`
- Any other exception → `[]`

Callers treat empty list as "I don't have info on that" and respond accordingly.

---

## Provider Registration

### ensure_kb_provider() — Auto-Setup

Located in `utils/providers_store.py`, this function runs during `AgentRuntimeHandler.__init__()`. It is **idempotent** — safe to call on every startup.

**Step 1: Seed the provider entry**

If no provider named `local-kb` exists in `providers.yaml`, it adds:

```yaml
- name: local-kb
  base_url: http://localhost:18790/v1
  api_key: "***"
  default_model: local-kb
  caller: openai
  supports_tools: false
  supports_streaming: false
  max_tokens: 4096
```

**Step 2: Patch the Auxilium agent**

Loads the helper agent definition (role `helper`) from `agents/*.yaml`. If the agent's `llm_name` is empty, sets it to `local-kb`. This enables a fresh-install user to get KB-backed help without any configuration.

If the agent already has a provider (including `local-kb`), the patch is skipped — existing configurations are never overridden.

---

## The Fallback Chain in Detail

### How It Works

When the KB server returns `[KB_OUT_OF_SCOPE]`, the agent runtime detects it and retries with an external provider. This is implemented in `AgentRuntime._run_loop()` (in `agent/runtime.py`).

### Step-by-Step

1. **Primary call** — The conversation uses model `local-kb`. The runtime calls the KB server.
2. **Sentinel detection** — The response text content is `[KB_OUT_OF_SCOPE]`.
3. **Guard check** — The fallback only triggers if:
   - `text_content == KB_OUT_OF_SCOPE`
   - `self._config.fallback_provider` is set (not `None`)
   - `conv._fallback_attempted` is `False` (one-shot guard)
4. **Model swap** — `conv.model` is temporarily changed to the fallback model:
   - If `fallback_model` is configured, use it (e.g. `openrouter/auto`)
   - Otherwise, construct from `fallback_provider/default_model`
5. **Fallback call** — `_call_llm()` runs again with the new model. The external provider processes the question normally.
6. **Restore** — `conv.model` is restored to the original (`local-kb`) in a `finally` block.
7. **One-shot flag** — `conv._fallback_attempted` is set to `True` to prevent loops. It is reset on each new user message.

### Configuration

Fallback is configured at the `AgentConfig` level (from `agent/config.py`):

```python
fallback_provider: str | None = None   # e.g. "openrouter"
fallback_model: str | None = None      # e.g. "openrouter/auto"
```

In the Agent Builder UI, the **Fallback Provider** dropdown lets you select from configured providers. When set, out-of-scope KB questions are automatically retried with that provider.

### What Happens Without a Fallback Provider

If `fallback_provider` is `None` (the default on fresh install), the `[KB_OUT_OF_SCOPE]` sentinel is passed through as the response text. The user sees the literal `[KB_OUT_OF_SCOPE]` in the chat, indicating the KB couldn't answer and no fallback was configured.

---

## Rebuilding the KB Index

### When to Rebuild

- After updating or adding `knowledge/*.md` files
- After upgrading CrabCakes (documentation may have changed)
- If KB results seem stale or incorrect
- If the KB server won't start (index files missing)

### How to Rebuild

```bash
cd /path/to/crabcakes
python3 scripts/rebuild_kb_index.py
```

### Options

```bash
# Use a different embedding model
python3 scripts/rebuild_kb_index.py --model sentence-transformers/all-MiniLM-L6-v2

# Output to a custom directory
python3 scripts/rebuild_kb_index.py --out /tmp/kb_index/
```

### What It Does

1. Reads all `.md` files from the `knowledge/` directory
2. Splits each file into chunks by `##` level-2 headings
3. Embeds each chunk with the configured model
4. L2-normalizes all embeddings
5. Writes `chunks.json` and `embeddings.npy` to `knowledge/.index/`

### Requirements

- `sentence-transformers` package: `pip install sentence-transformers`
- `numpy` package: `pip install numpy`
- ~130MB model download on first run (cached for subsequent runs)

### Idempotency

Re-running on unchanged KB content produces byte-identical output (deterministic model + same inputs → same embeddings).

---

## Agent Builder UI for Fallback Provider

In the Agent Builder dialog (accessible from the Agents tab):

1. Edit or create an agent
2. Look for the **Fallback Provider** dropdown
3. Select from configured providers (e.g. `openrouter`, `openai`, `anthropic`)
4. Optionally set a specific fallback model
5. Save the agent

The fallback configuration is stored in the agent's YAML definition and loaded into `AgentConfig` at runtime.

---

## Troubleshooting KB Issues

### KB Server Not Starting

**Check 1:** Is the index available?

```bash
ls knowledge/.index/chunks.json knowledge/.index/embeddings.npy
```

If missing, rebuild: `python3 scripts/rebuild_kb_index.py`

**Check 2:** Is `sentence-transformers` installed?

```bash
python3 -c "from sentence_transformers import SentenceTransformer; print('OK')"
```

If not: `pip install sentence-transformers`

**Check 3:** Is port 18790 available?

```bash
lsof -i :18790
```

If another process holds the port, kill it or restart CrabCakes.

**Check 4:** Check debug logs:

```bash
CRABCAKES_DEBUG=1 python3 main.py 2>&1 | grep kb_server
```

### KB Returns [KB_OUT_OF_SCOPE] for Everything

1. Rebuild the index (content may be stale)
2. Verify `knowledge/*.md` files have proper `##` headings
3. Check debug logs for `kb_lookup` results and scores:
   ```
   CRABCAKES_DEBUG=1 python3 main.py 2>&1 | grep kb_lookup
   ```
4. The confidence threshold (0.55) may be too high for some content types — this is by design to reduce false positives

### Auxilium Uses External Provider Instead of KB

If the Auxilium agent was previously configured with an external provider, `ensure_kb_provider()` will not override it (the patch only fires when `llm_name` is empty). To switch back to KB:

1. Open Agent Builder for the Auxilium agent
2. Change the LLM Provider to `local-kb`
3. Save

Or edit the agent YAML directly and set `llm_name: local-kb`.

### Health Check

Verify the KB server is running:

```bash
curl http://localhost:18790/health
# Should return: {"status": "ok"}
```
