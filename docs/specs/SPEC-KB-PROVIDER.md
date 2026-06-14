# SPEC: KB Provider — Local HTTP Server Wrapping kb_lookup

**Date:** 2026-06-14
**Author:** QTR (builder), directed by Qaster (supervisor)
**Parent proposal:** `docs/proposals/PROPOSAL-auxilium-three-tier-help-agent.md`
**Status:** Draft — pending Captain approval
**Phase:** KB Provider architecture
**Effort:** ~3-4 days

---

## Goal

Wire the existing KB lookup module (`agent/kb_lookup.py`) into the agent runtime by wrapping it in a local HTTP server that mimics the OpenAI `/v1/chat/completions` API. The runtime calls it as a standard OpenAI-compatible provider — **zero runtime changes needed**.

This connects the dead KB index (built, indexed, never queried) to the Auxilium agent's response path via the existing provider abstraction.

---

## Scope (in)

- **KB HTTP server** (`agent/kb_server.py`) — localhost server wrapping `kb_lookup`, responding to `/v1/chat/completions`
- **KB provider auto-registration** — `local-kb` provider seeded into `providers.yaml` on first launch if empty
- **Agent fallback_provider field** — agent YAML gets optional `fallback_provider`; agent editor dialog gets a dropdown
- **Runtime fallback chain** — agent tries primary provider, falls back on out-of-scope response
- **Out-of-scope detection** — KB server returns a sentinel message when no chunks match

## Scope (out)

- KB content expansion (Tier 2/3 knowledge files)
- LLM synthesis layer (KB server returns raw chunks, no rephrasing)
- Streaming support (blocking HTTP only — KB lookup is <500ms)
- Tool calling from KB server (KB server never calls tools)
- Multi-user / remote access (localhost only)
- TLS/SSL (loopback only, no encryption needed)

---

## Architecture constraints (from ARCHITECTURE.md)

| Rule | Source | Implication |
|---|---|---|
| `agent/` = no UI dependencies | §2 | `kb_server.py` in `agent/` — pure Python, no GTK |
| `agent/` = no network at import time | §2 | Server starts explicitly via `start_kb_server()`, not on import |
| Callbacks are the communication mechanism | §5 | Server lifecycle managed by `AgentRuntimeHandler`, not `ui/window.py` directly |
| New modules → update ARCHITECTURE.md | §0 | All new files documented in same commit |
| Tests in `tests/` | §8.5 | `test_kb_server.py`, `test_kb_provider_registration.py` |
| `snake_case.py` for all Python files | §6 | `kb_server.py` |

---

## Component 1: KB HTTP Server (`agent/kb_server.py`)

### Purpose

A lightweight HTTP server that listens on `localhost:18790` and responds to `/v1/chat/completions` requests by calling `kb_lookup()` with the last user message. Returns a response in OpenAI Chat Completions format so `_call_openai()` in the runtime can parse it without modification.

### API contract

**Endpoint:** `POST /v1/chat/completions`

**Request** (standard OpenAI format — fields the server reads):
```json
{
  "model": "local-kb",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "How do I install on Ubuntu?"}
  ]
}
```

**Response — KB hit** (chunks found above `min_score`):
```json
{
  "id": "chatcmpl-kb-<uuid>",
  "object": "chat.completion",
  "model": "local-kb",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Based on the CrabCakes knowledge base:\n\n---\n**Source:** knowledge/install.md :: Installing on Ubuntu\n\n<chunk text here>\n\n---\n**Source:** knowledge/install.md :: Verifying GTK4\n\n<chunk text here>"
    },
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0}
}
```

**Response — out-of-scope** (no chunks above `min_score`):
```json
{
  "id": "chatcmpl-kb-<uuid>",
  "object": "chat.completion",
  "model": "local-kb",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "[KB_OUT_OF_SCOPE]"
    },
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0}
}
```

### Sentinel value

`[KB_OUT_OF_SCOPE]` — constant string the runtime fallback chain checks. When the primary provider is `local-kb` and returns this sentinel, the runtime retries with the `fallback_provider`.

### Server implementation

```
agent/kb_server.py

Public API:
    start_kb_server(port=18790) -> threading.Thread
    stop_kb_server() -> None
    is_kb_server_running() -> bool
    KB_SERVER_PORT = 18790
    KB_OUT_OF_SCOPE = "[KB_OUT_OF_SCOPE]"
```

**Design:**
- Uses `http.server.HTTPServer` + `BaseHTTPRequestHandler` (stdlib only)
- Runs in a daemon thread (killed when app exits)
- Binds to `127.0.0.1` only (no external access)
- Single-threaded request handling (KB lookup is <500ms, no concurrency needed)
- Calls `kb_lookup(question, top_k=5, min_score=0.35)` — slightly higher threshold than default to reduce noise

**Error handling:**
- KB index missing → return `[KB_OUT_OF_SCOPE]` (fail soft — fallback provider handles it)
- `sentence-transformers` not installed → return `[KB_OUT_OF_SCOPE]`
- Malformed request body → HTTP 400 with `{"error": {"message": "..."}}`
- Wrong endpoint → HTTP 404
- Wrong method → HTTP 405

**Message extraction:**
- Extract the last `{"role": "user"}` message from the request's `messages` array
- Use its `content` as the question for `kb_lookup()`
- If no user message found, return `[KB_OUT_OF_SCOPE]`

**Response formatting:**
- Prefix: `"Based on the CrabCakes knowledge base:\n\n"`
- Each chunk: `"---\n**Source:** {source} :: {section}\n\n{text}\n\n"`
- Concatenate all chunks into one `content` string

### Lifecycle

- **Start:** Called from `AgentRuntimeHandler.__init__` (or app activation) via `start_kb_server()` if KB index is available
- **Stop:** Called from `AgentRuntimeHandler.shutdown` or app `do_shutdown`
- **Health check:** `GET /health` returns `{"status": "ok"}` — used by startup to verify the server is ready

---

## Component 2: KB Provider Auto-Registration

### Purpose

Ensure `local-kb` appears in `providers.yaml` automatically so the runtime can select it without manual configuration.

### Trigger

On app startup (after gateway connect), if `providers.yaml` is empty OR does not contain a provider named `local-kb`, seed it:

```python
ProviderConfig(
    name="local-kb",
    base_url="http://localhost:18790/v1",
    api_key="local",          # placeholder — KB server doesn't check auth
    default_model="local-kb",
    caller="openai",          # OpenAI-compatible API format
    supports_tools=False,     # KB server never calls tools
    supports_streaming=False, # blocking only
    max_tokens=4096,
)
```

### Implementation

Add to `utils/providers_store.py`:

```python
def ensure_kb_provider() -> None:
    """Seed local-kb provider if missing. Idempotent."""
    providers = load_providers()
    if any(p.name == "local-kb" for p in providers):
        return
    kb_provider = ProviderConfig(
        name="local-kb",
        base_url="http://localhost:18790/v1",
        api_key="local",
        default_model="local-kb",
        caller="openai",
        supports_tools=False,
        supports_streaming=False,
        max_tokens=4096,
    )
    providers.append(kb_provider)
    save_providers(providers)
```

Called from `AgentRuntimeHandler.__init__` or `ConnectionSyncHandler.on_connect` — after providers are loaded but before the agent runtime starts.

### Interaction with first-run wizard

If the wizard is showing (no real provider configured), `local-kb` should still be seeded so the agent runtime has a provider to call. The wizard's `is_auxilium_wizard_needed()` already checks `agents/auxilium.yaml` — the presence of `local-kb` in `providers.yaml` alone does NOT suppress the wizard. The wizard only completes when a real provider (openrouter, ollama, BYOK) is configured.

---

## Component 3: Agent Fallback Provider

### Purpose

Allow agents to specify a fallback provider used when the primary returns `[KB_OUT_OF_SCOPE]`. This enables the Auxilium pattern: try KB first, fall back to real LLM for questions the KB can't answer.

### Agent YAML schema change

Add optional `fallback_provider` field to agent YAML:

```yaml
# agents/auxilium.yaml
name: Auxilium
provider: local-kb
model: local-kb
fallback_provider: openrouter
fallback_model: openrouter/owl-alpha
```

### Agent definition parsing (`utils/agent_defs.py`)

- `_parse_agent_file()` reads `fallback_provider` and `fallback_model` from YAML
- Missing fields default to `None` (no fallback)
- Validation: if `fallback_provider` is set, it must exist in `providers.yaml` at runtime (warn if missing, don't crash)

### Agent editor dialog (`ui/views/agent_builder_dialog.py`)

- Add "Fallback Provider" dropdown below the existing provider dropdown
- Populated from the same provider list as the primary dropdown
- Includes a "None" option (default)
- When provider changes, update available models in a linked "Fallback Model" field
- Only visible when primary provider is `local-kb` (hidden otherwise — fallback is a KB-specific pattern)

### AgentConfig / Conversation changes

- `AgentConfig` gets `fallback_provider: str | None = None` and `fallback_model: str | None = None`
- `Conversation` gets `fallback_provider` and `fallback_model` fields, set at `create_conversation()` time
- `create_conversation()` reads these from the agent definition

---

## Component 4: Runtime Fallback Chain

### Purpose

When the primary provider returns `[KB_OUT_OF_SCOPE]`, retry the same user message with the fallback provider.

### Implementation in `_run_loop()` (`agent/runtime.py`)

After extracting text content from the LLM response:

```python
# After _extract_text_content returns
if (
    text_content == KB_OUT_OF_SCOPE
    and conv.fallback_provider
    and not getattr(conv, "_fallback_attempted", False)
):
    # Mark to prevent infinite fallback loops
    conv._fallback_attempted = True

    # Temporarily switch provider for this iteration
    original_model = conv.model
    conv.model = conv.fallback_model

    # Retry the LLM call with fallback provider
    response = self._call_llm(session_key, messages, tools)
    text_content = _extract_text_content(response, loop_provider)

    # Restore original model for future iterations
    conv.model = original_model

    # Re-extract tool calls from fallback response
    tool_calls_raw = _extract_tool_calls(response, loop_provider)
```

### Guard rails

1. **One-shot fallback:** `_fallback_attempted` flag prevents retrying more than once per user message. Reset on new `send_message()`.
2. **No nested fallback:** If the fallback provider also returns `[KB_OUT_OF_SCOPE]`, treat as normal text response (show it to user).
3. **Tool calls from fallback:** If the fallback provider returns tool calls, process them normally — the fallback is a real LLM and can use tools.

### Streaming consideration

When streaming (`on_text_delta` is registered), the KB server does NOT support streaming. The runtime should detect `caller=openai` + `base_url=localhost` and use blocking mode for KB calls, then switch to streaming for the fallback provider. This is handled by checking `supports_streaming` on the provider config:

```python
# In _call_llm, before choosing streaming vs blocking:
provider_cfg = config.providers.get(provider_name)
if self._on_text_delta is not None and provider_cfg and provider_cfg.supports_streaming:
    # Use streaming path
else:
    # Use blocking path
```

---

## Component 5: Out-of-Scope Detection

### Purpose

Reliably detect when the KB server has no relevant chunks for a question.

### Mechanism

The KB server returns `[KB_OUT_OF_SCOPE]` as the entire `content` field when:
1. `kb_lookup()` returns an empty list (no chunks above `min_score`)
2. KB index files are missing
3. `sentence-transformers` is not installed
4. No user message in the request

### Constant

```python
# agent/kb_server.py
KB_OUT_OF_SCOPE = "[KB_OUT_OF_SCOPE]"
```

Imported by `agent/runtime.py` for the fallback chain check:

```python
from agent.kb_server import KB_OUT_OF_SCOPE
```

### Why a sentinel string (not an HTTP status or header)?

The runtime's `_call_openai()` treats non-200 responses as errors (`RuntimeError`). Using a sentinel string in the response body means:
- No runtime changes to error handling
- The fallback chain checks one string equality
- The sentinel is visible in logs for debugging
- If a user somehow sees `[KB_OUT_OF_SCOPE]`, it's clear what happened

### Threshold tuning

Default `min_score` for the KB server is `0.35` (higher than `kb_lookup`'s default of `0.3`). This reduces false positives where marginally-related chunks trigger a confident-but-wrong response. The threshold is a constant in `kb_server.py`, not user-configurable in this phase.

---

## Data Flow

```
User types: "How do I install on Ubuntu?"
     │
     ▼
AgentRuntimeHandler.on_user_input()
     │
     ▼
AgentRuntime.send_message(session_key, text)
     │
     ▼
_run_loop() spawns (background thread)
     │
     ├─ build messages (system + history + user)
     │
     ├─ _call_llm()
     │    ├─ provider = "local-kb"
     │    ├─ caller_key = "openai"
     │    ├─ _call_openai("http://localhost:18790/v1", ...)
     │    │
     │    │    ┌─────────────────────────────────────┐
     │    │    │ KB HTTP Server (localhost:18790)    │
     │    │    │                                     │
     │    │    │ 1. Parse messages → last user msg   │
     │    │    │ 2. kb_lookup("install on Ubuntu")   │
     │    │    │ 3. Chunks found?                    │
     │    │    │    ├─ YES → format chunks as text   │
     │    │    │    └─ NO  → [KB_OUT_OF_SCOPE]       │
     │    │    │ 4. Return OpenAI-format response    │
     │    │    └─────────────────────────────────────┘
     │    │
     │    └─ response parsed by _extract_text_content()
     │
     ├─ Check: text_content == "[KB_OUT_OF_SCOPE]"?
     │    ├─ NO  → normal response path (fire on_response_complete)
     │    └─ YES → fallback chain
     │         ├─ conv.fallback_provider set?
     │         │    ├─ NO  → show [KB_OUT_OF_SCOPE] as response
     │         │    └─ YES → retry _call_llm with fallback model
     │         │              ├─ _call_openai("https://openrouter.ai/api/v1", ...)
     │         │              └─ normal response from real LLM
     │         └─ fire on_response_complete with fallback response
     │
     └─ done
```

---

## Deliverables

| # | File | Type | Description |
|---|---|---|---|
| 1 | `agent/kb_server.py` | New | KB HTTP server wrapping `kb_lookup` |
| 2 | `utils/providers_store.py` | Edit | Add `ensure_kb_provider()` function |
| 3 | `utils/agent_defs.py` | Edit | Parse `fallback_provider` / `fallback_model` from YAML |
| 4 | `agent/config.py` | Edit | Add `fallback_provider` / `fallback_model` to AgentConfig |
| 5 | `agent/runtime.py` | Edit | Fallback chain in `_run_loop()`, streaming guard in `_call_llm()` |
| 6 | `models/conversation.py` | Edit | Add `fallback_provider` / `fallback_model` to Conversation |
| 7 | `ui/views/agent_builder_dialog.py` | Edit | Fallback provider dropdown (visible only when primary is local-kb) |
| 8 | `ui/handlers/agent_runtime_handler.py` | Edit | Call `start_kb_server()` on init, `stop_kb_server()` on shutdown |
| 9 | `tests/test_kb_server.py` | New | Server unit tests (request parsing, response format, OOB sentinel) |
| 10 | `tests/test_kb_provider_registration.py` | New | Provider auto-registration tests |
| 11 | `ARCHITECTURE.md` | Edit | Document `kb_server.py` in §3 and §13 |

---

## Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-KB-1 | KB server starts on app launch if KB index exists | `is_kb_server_running()` returns True after `AgentRuntimeHandler.__init__`; `GET http://localhost:18790/health` returns 200 |
| AC-KB-2 | KB server responds to `/v1/chat/completions` in OpenAI format | `curl -X POST localhost:18790/v1/chat/completions -d '{"model":"local-kb","messages":[{"role":"user","content":"install"}]}'` returns valid `choices[0].message.content` |
| AC-KB-3 | KB server returns `[KB_OUT_OF_SCOPE]` when no chunks match | Query with irrelevant text ("quantum physics"); response content is exactly `[KB_OUT_OF_SCOPE]` |
| AC-KB-4 | `local-kb` appears in providers.yaml after first launch | `load_providers()` includes entry with `name="local-kb"` |
| AC-KB-5 | Agent YAML supports `fallback_provider` field | Parse a test YAML with `fallback_provider: openrouter`; verify `_parse_agent_file()` returns it |
| AC-KB-6 | Runtime falls back when primary returns `[KB_OUT_OF_SCOPE]` | Unit test: mock `_call_llm` returning sentinel, verify fallback provider is called |
| AC-KB-7 | Fallback is one-shot (no infinite loop) | Unit test: fallback provider also returns sentinel; verify no third call |
| AC-KB-8 | Agent editor shows fallback dropdown only when primary is local-kb | Manual: select local-kb as primary → dropdown appears; select openrouter → dropdown hides |
| AC-KB-9 | KB server shuts down on app exit | `stop_kb_server()` → `is_kb_server_running()` returns False; port 18790 is released |

---

## Test Plan

### `tests/test_kb_server.py`

- **test_health_check:** `GET /health` returns 200 `{"status": "ok"}`
- **test_chat_completions_kb_hit:** POST with install-related question → response has `choices[0].message.content` containing chunk text
- **test_chat_completions_out_of_scope:** POST with irrelevant question → content is exactly `[KB_OUT_OF_SCOPE]`
- **test_chat_completions_no_user_message:** POST with only system message → content is `[KB_OUT_OF_SCOPE]`
- **test_chat_completions_malformed_body:** POST with invalid JSON → HTTP 400
- **test_chat_completions_wrong_method:** GET on `/v1/chat/completions` → HTTP 405
- **test_chat_completions_wrong_path:** POST on `/v1/wrong` → HTTP 404
- **test_server_lifecycle:** `start_kb_server()` → `is_kb_server_running()` is True; `stop_kb_server()` → False
- **test_kb_server_uses_kb_lookup:** Mock `kb_lookup` → verify it's called with the last user message

### `tests/test_kb_provider_registration.py`

- **test_ensure_kb_provider_seeds_when_empty:** Empty providers.yaml → `ensure_kb_provider()` adds local-kb entry
- **test_ensure_kb_provider_idempotent:** Call twice → still one local-kb entry
- **test_ensure_kb_provider_preserves_existing:** providers.yaml with openrouter → `ensure_kb_provider()` adds local-kb without removing openrouter

### `tests/test_runtime_fallback.py` (or add to existing runtime tests)

- **test_fallback_on_out_of_scope:** Mock primary `_call_llm` returning `[KB_OUT_OF_SCOPE]`; verify fallback is called
- **test_no_fallback_without_config:** No `fallback_provider` set → sentinel text is returned as-is
- **test_fallback_one_shot:** Fallback also returns sentinel → no third call; sentinel shown to user
- **test_fallback_reset_on_new_message:** Send two messages; first triggers fallback; second can trigger fallback again

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Port 18790 already in use | Low | `start_kb_server()` catches `OSError`, logs warning, continues without KB |
| `sentence-transformers` not installed | Medium (fresh installs) | KB server returns `[KB_OUT_OF_SCOPE]`; fallback provider handles it transparently |
| KB index stale (built from old docs) | Medium | `scripts/rebuild_kb_index.py` re-run manually; future phase could auto-rebuild on file change |
| Fallback provider also fails | Low | One-shot guard prevents cascade; error shown to user normally |
| Sentinel string leaks to user | Low | Runtime checks and replaces `[KB_OUT_OF_SCOPE]` before dispatching `on_response_complete`; if no fallback configured, shows a friendly "I don't have info on that" message instead of the raw sentinel |

---

## Out-of-Scope (Explicit Exclusions)

- **KB server streaming:** KB lookups are <500ms; blocking is fine
- **KB server authentication:** Localhost only; no auth needed
- **Multi-model KB:** Single embedding model (`bge-small-en-v1.5`); no model selection
- **KB server as general-purpose proxy:** Only handles `/v1/chat/completions`; no embeddings endpoint, no models list
- **Auto-rebuild on KB file changes:** Manual `rebuild_kb_index.py` only in this phase
- **Fallback to more than one provider:** Single fallback only; no chain of length >2

---

## Phase Sequencing

This spec is implementable in one phase. Suggested commit order:

1. `agent/kb_server.py` + `tests/test_kb_server.py` (standalone, testable)
2. `utils/providers_store.py` `ensure_kb_provider()` + tests
3. `agent/config.py` + `models/conversation.py` fallback fields
4. `agent/runtime.py` fallback chain in `_run_loop()`
5. `utils/agent_defs.py` YAML parsing
6. `ui/views/agent_builder_dialog.py` dropdown
7. `ui/handlers/agent_runtime_handler.py` server lifecycle wiring
8. Integration test: full path from user message → KB server → response

---

## References

- `agent/kb_lookup.py` — KB lookup module (existing, unchanged)
- `agent/runtime.py:104-148` — `_call_openai()` (the caller that will hit our server)
- `agent/runtime.py` `_run_loop()` — tool loop where fallback chain hooks in
- `models/providers.py` — `ProviderConfig` dataclass
- `utils/providers_store.py` — provider YAML persistence
- `agent/config.py:29-72` — `LLMProviderConfig`, `AgentConfig`
- `docs/specs/SPEC-auxilium-tier-1.md` — parent spec for Auxilium Tier 1
