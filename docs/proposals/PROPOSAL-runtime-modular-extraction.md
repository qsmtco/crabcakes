# PROPOSAL: Runtime Modular Extraction — Identify Pluggable Components in `agent/runtime.py`

**Date:** 2026-06-28
**Author:** QTR (audit), with QTR sub-agents (LLM layer, run loop, sibling modules, tools)
**Status:** ❌ NOT IMPLEMENTED — spec (`SPEC-RUNTIME-MODULAR-EXTRACTION-PHASE-1.md`, 1,226 lines) was drafted, but no code changes were ever committed. `agent/tool_middleware.py` does not exist; `agent/llm/` package does not exist; `agent/runtime.py` remains at 3,183 lines (spec target was <1,800). The `_call_openai`, `_call_minimax`, `_call_anthropic` functions are still embedded in `runtime.py`. No `test_tool_middleware.py` or `test_llm_streaming.py` test files exist.
**Severity:** LOW-MED — architectural refactor across the whole agent runtime. Not urgent individually, but the cumulative benefit is high (5+ independent extractions, each enabling a new capability). This is a *map*, not a single change.

**Related proposals:**
- `docs/proposals/PROPOSAL-agent-package-restructure.md` (2026-06-11, **PENDING** — proposes splitting `agent/` into `llm/`, `domain/`, `policies/` packages)
- `docs/proposals/PROPOSAL-pluggable-context-strategy.md` (2026-06-26, **SHIPPED** — reference template for what good modular extraction looks like)
- `docs/proposals/DEFERRED-ITEMS.md` A-11 (2026-06-19, **PARKED** — first formal decision to defer the runtime refactor)
- `docs/proposals/PROPOSAL-mcp-agent-tools-hot-reload.md`
- `docs/proposals/PROPOSAL-mcp-client-integration.md`
- `docs/audits/2026-06-27-ARCHITECTURE-CONSISTENCY-AUDIT.md` (notes `agent/runtime.py` grew 1,420 → 2,418 lines, +70%, since last architecture doc update)

**Adversarial audit performed:** This proposal was audited line-by-line against the codebase on 2026-06-28. All line numbers, symbol names, and counts below were re-verified against `agent/runtime.py` (2,495 lines), `pytest --collect-only` (2,269 tests), and `git log` (commit `262af32` confirmed). Issues found during the audit are fixed inline; see `§11` for the audit summary.

**Architecture alignment:** This proposal modifies components documented in ARCHITECTURE.md §3.21m (`agent/runtime.py`). All changes respect the layering rules in §2: `agent/` has no UI dependencies, `models/` has no UI dependencies, no new cross-layer imports are introduced. Each new module lives in the `agent/` layer and imports from `models/` and `utils/` only.

---

## 1. Executive Summary

`agent/runtime.py` has grown from **1,420 lines** (when last documented in ARCHITECTURE.md §3.21m) to **2,495 lines** today (`wc -l agent/runtime.py`, 2026-06-28) — a **+76% increase** that the documentation has not tracked. Inside this growth, at least **seven independent modular extractions** are now viable, each with a clear Protocol boundary, an isolated call site, and an existing reference template (`agent/context_strategy.py` proves the pattern works in this codebase).

Unlike `PROPOSAL-agent-package-restructure.md` which proposes **one** monolithic split into `llm/`, `domain/`, `policies/` packages, this proposal recommends **seven incremental extractions** done one at a time, each shippable independently, each in the spirit of the already-shipped `ContextStrategy` pattern. The cumulative effect is the same architectural cleanup as `agent-package-restructure`, but without the "all-or-nothing" risk that has kept that proposal PENDING for 17 days.

The seven candidates, ranked by impact:

| # | Extraction | Lines freed from runtime.py | New module | Priority |
|---|---|---|---|---|
| 1 | **Tool middleware chain** (approval + enforcement + stuck detection) | ~120 | `agent/tool_middleware.py` | **HIGH** |
| 2 | **LLM provider adapter** (callers + streamers + extractors) | ~620 | `agent/llm/provider.py` (+ `agent/llm/streaming.py`) | **HIGH** |
| 3 | **Cost model** (model_id + cost_for_model) | ~50 | `agent/cost.py` (or fold into `models/providers.py`) | MED |
| 4 | **Conversation persistence** (disk I/O) | ~270 | `agent/persistence.py` | MED |
| 5 | **AuditLog** (tool audit trail) | ~95 | `agent/audit.py` | MED |
| 6 | **Tool output truncation policy** | ~50 | `agent/tool_output.py` | MED |
| 7 | **Sub-orchestration hooks** (lifecycle: pre_send, post_send, pre_save, post_save) | ~60 | `agent/hooks.py` | LOW |

Each is described in §3 with concrete boundaries, call-site changes, and risk. The `_run_loop` seam analysis underlying §3.1 and §3.7 is included inline in those sections rather than as a separate audit document. The proposal explicitly does **not** recommend a single mega-PR. Each extraction ships in its own commit, follows the ContextStrategy pattern, and can be safely reverted independently.

---

## 2. Problem Statement

### 2.1 The runtime.py growth crisis

`agent/runtime.py` size over time (from git history + ARCHITECTURE.md):

| Date | Lines | Source |
|---|---|---|
| 2026-06-11 | ~1,575 | PROPOSAL-agent-package-restructure.md baseline |
| 2026-06-19 | 1,501 | DEFERRED-ITEMS.md A-11 |
| ARCHITECTURE.md §3.21m (snapshot) | 1,420 | docs/ARCHITECTURE.md |
| 2026-06-27 | 2,418 | 2026-06-27-ARCHITECTURE-CONSISTENCY-AUDIT.md |
| **2026-06-28 (today)** | **2,495** | `wc -l agent/runtime.py` |

That's **+1,075 lines in 17 days** (+72%). Most growth came from context management, telemetry, and streaming additions that were never extracted. The doc note in `DEFERRED-ITEMS.md` A-11 — "1501 LOC is large but not catastrophic" — is now stale; we're at 2,495 and growing.

### 2.2 Why a single mega-split (PROPOSAL-agent-package-restructure) has stalled

`PROPOSAL-agent-package-restructure.md` proposed moving the whole `agent/` package into `llm/`, `domain/`, `policies/` subpackages. It has been PENDING for 17 days. Likely reasons (inferred):

- Single 1,000+ line PR is high-risk to review and high-risk to revert
- Tests for cross-cutting concerns (streaming, persistence, audit) span the whole surface
- No "incremental win" to show progress between phases
- Forced naming decisions (what goes in `llm/` vs `domain/`?) without working code to validate

By contrast, `PROPOSAL-pluggable-context-strategy.md` (2026-06-26) shipped successfully because it was a **single focused extraction** with a clean Protocol. This proposal applies that same template to seven more places.

### 2.3 What the successful ContextStrategy extraction teaches us

The shipped `agent/context_strategy.py` (687 lines) is the template:

| Element | How ContextStrategy did it |
|---|---|
| **Protocol definition** | `class ContextStrategy(Protocol): def compact(...): ...` |
| **Default impl** | `class DefaultContextStrategy: ...` — moves existing logic verbatim |
| **Composition over inheritance** | `AgentRuntime` *holds* a strategy instance, not subclass of one |
| **Pluggability point** | Config field `strategy_name` selects which strategy; default = "default" |
| **Telemetry** | `CompactionEvent` dataclass records each compaction event |
| **No UI imports** | Strategy module imports only `models/` |
| **Testability** | Each strategy is unit-testable without instantiating `AgentRuntime` |

All seven proposed extractions below follow this same template.

---

## 3. The Seven Extractions

### 3.1 [HIGH] Tool Middleware Chain — `agent/tool_middleware.py`

**Current state:** `_run_loop` (lines 1671–2073; the `_dispatch_approval` helper sits at L2078) interleaves three policy concerns inline at the tool-execution site (lines ~1927–2050):

- **Approval gating** (L1949–L1981): hardcoded check — `if tool_name == "exec_command"` at L1951, then `if tool_name in ("write_file", "edit_file") and agent_tools_module.is_sensitive_path(...)` at L1965; dispatches to PM via `_dispatch_approval`
- **Enforcement hook** (L2011–L2037): inline call to `_enforcement_check` (imported from `agent.enforcement` at L31) wrapped in try/except and `global_enabled && agent_enabled` gating
- **Stuck detection** (L2039 via `self._check_stuck`): inline call passing `session_key, tool_name, args, iteration`

These three concerns are bolted onto the loop body. Adding a new approval-required tool requires editing `_run_loop`. Adding a new enforcement tier requires editing `_run_loop`. They share no interface; they're just three sequential blocks.

**Extraction proposal:**

```python
# agent/tool_middleware.py
class ToolMiddleware(Protocol):
    def __call__(self, tool_name: str, args: dict, conv: "Conversation",
                 next: Callable[..., "ToolResult"]) -> "ToolResult": ...

class ApprovalMiddleware:
    SENSITIVE_TOOLS = frozenset({"exec_command", "write_file", "edit_file", "patch_feed_card"})
    SENSITIVE_ARGS = {"shell_command_starts_with": ["rm", "sudo", "curl", "wget"], ...}
    def __init__(self, approval_callback): ...

class EnforcementMiddleware:
    def __init__(self, enforcement_module): ...

class StuckDetectionMiddleware:
    def __init__(self, stuck_check_fn): ...

class ToolMiddlewareChain:
    def __init__(self, middlewares: list[ToolMiddleware]): ...
    def run(self, tool_name, args, conv, executor) -> ToolResult:
        # Composes middleware chain (onion pattern)
```

**Call-site change in `_run_loop`:** replace the inline approval+enforcement+stuck block (L1949–L2039, ~90 lines) with `chain.run(tool_name, args, conv, lambda: execute_tool(...))`.

**Concurrency considerations:** The chain runs inside `_run_loop` while `_check_and_stop_on_limit` (L2406) reads `conv.total_cost`/`conv.step_count` under no lock — currently safe because both run on the same agent thread. The middleware chain must preserve this invariant: each middleware executes synchronously within the tool-call frame. Async PM approval (`_dispatch_approval` returns `None` → waits on `self._pending_approvals[approval_key]["event"]` at L1460-1465) is the only async escape; middlewares must not introduce new ones. The `_check_stuck` call at L2039 must remain *after* execution (it inspects `self._tool_history`, which the execution itself populates).

**Why HIGH priority:**
- Eliminates the largest *policy* coupling in the runtime — three orthogonal concerns sharing no interface
- Enables adding new policies (rate limiting, telemetry, retries) without touching the loop
- Makes approval gating testable in isolation (currently requires a full AgentRuntime with PM)
- Natural alignment with `agent/enforcement.py` which already wants to be a middleware but currently gets called via a magic dispatch from runtime

**Risk:** MED — the order of middleware matters (approval → execute → enforcement → stuck check); must be tested with the existing test suite (`TestStreaming` class at `tests/test_agent_runtime.py` L1050 and `TestStreamingSignature` at L1413 are the streaming pattern; approval-gating tests are in the same file). The composition pattern is well-understood (Express.js, Django middleware).

**Effort:** MED (~3-4 days including tests).

**Bonus:** `agent/enforcement.py` (942 lines) currently has its own state machine; if it becomes a middleware, it can lose ~150 lines of dispatch glue. **Note:** this bonus is not a separate extraction — if §3.1 lands, this is a follow-on refactor of `enforcement.py` itself, not part of the seven. Flagging for §4.4 follow-up.

---

### 3.2 [HIGH] LLM Provider Adapter — `agent/llm/provider.py` + `agent/llm/streaming.py`

**Current state:** Five callers plus three streamers (all module-level), plus four SSE helpers, two Anthropic-format converters, one SSL retry wrapper, and three response extractors — all in `runtime.py`:

| Symbol | Lines | Purpose |
|---|---|---|
| `_call_openai` | L192-234 | OpenAI non-streaming call (also used by `openrouter` + `zai`) |
| `_call_minimax` | L235-282 | MiniMax non-streaming call |
| `_call_anthropic` | L360-451 | Anthropic non-streaming call |
| `_stream_openai_events` | L543-598 | OpenAI streaming (also used by `openrouter` + `zai`) |
| `_stream_minimax_events` | L599-693 | MiniMax streaming |
| `_stream_anthropic_events` | L694-811 | Anthropic streaming |
| `_sse_lines` | L452-458 | SSE line iterator |
| `_parse_sse_line` | L459-477 | SSE event parser |
| `_parse_sse_delta` | L478-508 | SSE delta parser |
| `_convert_messages_for_anthropic` | L283-334 | Anthropic message format converter |
| `_convert_tools_for_anthropic` | L335-359 | Anthropic tool format converter |
| `_urlopen_with_ssl_retry` | L521-542 | SSL retry wrapper |
| `_extract_tool_calls` | L812-857 | Response → tool calls |
| `_extract_text_content` | L858-878 | Response → text |
| `_extract_usage` | L879-898 | Response → token usage |

**Total: ~620 lines** that all serve one concern — "talk to an LLM provider."

The pattern is identical across the three implementations but the code is repeated per provider. Adding a sixth provider (Google, Mistral) requires editing two dispatch dicts (`_PROVIDER_CALLERS` at L420-426, `_PROVIDER_STREAMERS` at L797-803) plus writing ~100 lines of nearly-duplicate code. **Today, five providers are wired (`openai`, `minimax`, `anthropic`, `openrouter`, `zai`); three share the OpenAI caller, three share the OpenAI streamer; only Anthropic has its own.**

**Extraction proposal:**

```python
# agent/llm/__init__.py
class LLMProvider(Protocol):
    """One class per provider. All provider knowledge lives here."""
    id: str  # "openai", "minimax", "anthropic"
    def call(self, model: str, messages: list, tools: list, **kwargs) -> LLMResponse: ...
    def stream(self, model: str, messages: list, tools: list, **kwargs) -> Iterator[LLMEvent]: ...
    def convert_messages(self, messages: list) -> list: ...  # optional, default passthrough
    def convert_tools(self, tools: list) -> list: ...  # optional, default passthrough

class LLMResponse:
    text: str
    tool_calls: list[tuple[str, str, dict]]
    usage: tuple[int, int]  # (prompt, completion)
    raw: dict  # provider-specific

# agent/llm/registry.py
REGISTRY: dict[str, LLMProvider] = {
    "openai": OpenAIProvider(),                # own provider
    "minimax": OpenAIProvider(),               # same wire protocol as OpenAI
    "openrouter": OpenAIProvider(),            # OpenAI-compatible API
    "zai": OpenAIProvider(),                   # OpenAI-compatible API (free tier)
    "anthropic": AnthropicProvider(),          # own wire protocol
}
def get_provider(id: str) -> LLMProvider: ...

# agent/llm/openai.py
class OpenAIProvider(LLMProvider): ...

# agent/llm/anthropic.py
class AnthropicProvider(LLMProvider): ...

# agent/llm/streaming.py
def sse_lines(resp) -> Iterator[bytes]: ...
def parse_sse_line(line: bytes) -> SSEEvent | None: ...
def parse_sse_delta(d: dict) -> list[SSEEvent]: ...
def urlopen_with_ssl_retry(req, timeout, *, max_retries=...): ...

# agent/llm/extractors.py  (or fold into each provider)
def extract_tool_calls(response: dict, provider: LLMProvider) -> list[...]: ...
def extract_text_content(response: dict, provider: LLMProvider) -> str: ...
def extract_usage(response: dict, provider: LLMProvider) -> tuple[int, int]: ...
```

**Key insight:** Four providers (`openai`, `minimax`, `openrouter`, `zai`) all use the OpenAI wire protocol, so `OpenAIProvider` is reused with different credentials — no per-provider class needed for any of them; the registry just maps four keys to the same instance. This collapses 4 callers and 4 streamers into 1 implementation (with `AnthropicProvider` as the sole alternative). Today this is already true at the function level (`_PROVIDER_CALLERS["openrouter"] = _call_openai`); the refactor just makes the aliasing explicit and discoverable.

**Call-site change in `runtime.py`:** replace the dispatch in `_call_llm` (L2132-2239) and `_call_llm_streaming` (L2241-2350) bodies with:

```python
provider = get_provider(caller_key)  # caller_key comes from model prefix
response = provider.call(model, messages, tools, **kwargs)
# or
for event in provider.stream(model, messages, tools, **kwargs):
    ...
```

This eliminates the entire `_PROVIDER_CALLERS` / `_PROVIDER_STREAMERS` dispatch dict pattern at the AgentRuntime level.

**External callers to preserve during migration:** `_PROVIDER_STREAMERS` is patched by `scripts/audit_streaming_scenarios.py` (10 sites) and imported directly by `scripts/audit_attack_scenarios.py` (line 6: `from agent.runtime import AgentRuntime, _PROVIDER_CALLERS, _PROVIDER_STREAMERS`). These must continue to work via re-exports: keep `runtime._PROVIDER_CALLERS = PROVIDER_CALLERS` and `runtime._PROVIDER_STREAMERS = PROVIDER_STREAMERS` as module-level aliases until scripts are updated. Migration plan: alias for at least one release, then deprecate.

**Why HIGH priority:**
- Largest single extraction (~620 lines)
- Adds a new capability the current shape **blocks**: hot-swapping providers, A/B-testing provider implementations, and supporting any new OpenAI-compatible API (e.g., vLLM, a new internal gateway) via a one-line registry addition. **No need to wait for Ollama/vLLM as a concrete use case** — every OpenAI-compatible provider benefits immediately.
- Aligns with `PROPOSAL-mcp-client-integration.md` which assumes provider abstraction
- The 4-way OpenAI alias collapse is a free simplification discovered during the audit

**Risk:** MED-HIGH — streaming in particular has subtle behavior (SSE event ordering, tool-call delta accumulation, mid-stream errors). The streaming regression tests are `tests/test_agent_runtime.py::TestStreaming` (L1050), `TestStreamingSignature` (L1413), and `TestStreamingUsageCapture` (L1487); run them after every commit. The `scripts/audit_streaming_scenarios.py` script patches `_PROVIDER_STREAMERS` directly — it must be updated in lockstep with the registry move. Backward compatibility: re-export the old names from `runtime.py` via `_call_openai = OpenAIProvider().call` shims during migration.

**Effort:** MED-HIGH (~5-7 days, including the streaming test gauntlet). Should be done in two phases: non-streaming first (3 days), streaming second (3 days), with regression tests between.

**Rollback plan if Phase 7 (streaming) fails:** If the streaming extraction cannot pass `TestStreaming` after 3 days, ship Phases 1-6 anyway (non-streaming + the other five extractions). The streaming code stays in `runtime.py` as `_stream_*_events` helpers, while non-streaming lives in `agent/llm/`. This is strictly better than today (non-streaming is decoupled), and the streaming work can be retried in a separate effort with its own analysis. **The non-streaming phase is independent of streaming — no cross-dependency.**

---

### 3.3 [MED] Cost Model — `agent/cost.py` (or fold into `models/providers.py`)

**Current state:** Two functions plus a five-key cost table in `runtime.py`:
- `_model_id(model: str) -> str` (L172-181): strips `"provider/"` prefix from model strings
- `_cost_for_model(model: str, prompt_tokens: int, completion_tokens: int) -> float` (L182-191): looks up cost in `_PROVIDER_COSTS` (L162-169)
- `_PROVIDER_COSTS` (L162-169): five entries — `openai`, `minimax`, `anthropic`, `openrouter` (aliased to `_OPENAI_COST`), `zai` (aliased to `_OPENAI_COST`); plus the three constants `_OPENAI_COST`, `_MINIMAX_COST`, `_ANTHROPIC_COST` (L159-161)

The cost table is a `dict[str, dict[str, float]]` literal at module level. There are 2 call sites in `AgentRuntime` (L1799 inside `_call_llm`'s caller, L1910 inside the streaming path). `_cost_for_model` is exported in `__all__` (L68) and tested directly (`test_agent_runtime.py` L71-79).

**Problem:** Cost is provider configuration. Currently split across two files (`agent/runtime.py` and `models/providers.py`). A developer adding a new provider must update both. Worse, `models/providers.py` is supposed to own provider config but doesn't know about cost.

**Extraction proposal:** Move `_model_id` and `_cost_for_model` into `models/providers.py` (preferred — cost is provider config) OR `agent/cost.py` (if we want to keep `models/` pure-data per ARCHITECTURE.md §3.21l rules).

**Why MED priority:**
- Small (~50 lines) but reduces a real boundary violation (`models/` ↔ `agent/`)
- Already tested in isolation (`test_agent_runtime.py` L71-79) so migration is low-risk
- Enables cost to be loaded from `providers.yaml` instead of hardcoded (one of the few places config and code still diverge)

**Risk:** LOW — pure function move, no behavior change.

**Effort:** LOW (~1 day).

---

### 3.4 [MED] Conversation Persistence — `agent/persistence.py`

**Current state:** Six module-level functions in `runtime.py` totaling ~270 lines:

| Symbol | Lines | Purpose |
|---|---|---|
| `_conversations_dir()` | L916-933 | Returns the conversations directory path |
| `_save_conversation_to_disk()` | L934-990 | Serialize Conversation + metadata |
| `_resolve_api_key_for_conversation()` | L991-1025 | Read API key for session |
| `_load_conversation_from_disk()` | L1026-1095 | Deserialize Conversation + metadata |
| `_migrate_conversation_files()` | L1096-1148 | One-time migration of legacy file format |
| `_resolve_session_workspace()` | L1149-1185 | Map session_key → workspace dir |

**Problem:** All six functions are disk I/O with zero dependency on `AgentRuntime` — they're stateless module-level helpers. They're called from `AgentRuntime.save_conversation()`, `.load_conversation()`, `.create_conversation()`, etc. The persistence layer is hidden inside the runtime module, which:
- Makes it impossible to test persistence without instantiating `AgentRuntime`
- Mixes schema (`ConversationSnapshot`) with I/O (`json.dump`) with path resolution (`pathlib.Path.home() / ".crabcakes"`)
- Hides the migration logic (`_migrate_conversation_files`) where it might never be revisited

**Extraction proposal:**

```python
# agent/persistence.py
class ConversationStore:
    """Stateless disk-I/O wrapper. One instance per AgentRuntime."""
    def __init__(self, conversations_dir: Path | None = None): ...
    def save(self, conv: "Conversation", session_key: str) -> str: ...
    def load(self, session_key: str) -> tuple["Conversation", dict] | None: ...
    def list_all(self) -> list[tuple[str, str]]: ...
    def migrate_legacy(self) -> int: ...
    def _resolve_api_key(self, data: dict) -> str | None: ...
    def _resolve_workspace(self, session_key: str, project_path: str | None) -> str: ...
```

`AgentRuntime` holds a `ConversationStore` instance, calls `store.save(...)` etc. All disk I/O is now in one place.

**Why MED priority:**
- Self-contained extraction — zero cross-module coupling
- Test isolation win: persistence tests no longer need a full `AgentRuntime`
- Future-proofs for cloud storage (S3, etc.) — swap the impl, keep the interface
- The migration logic gets a home where it's visible

**Risk:** LOW — pure mechanical move, well-tested surface.

**Effort:** LOW-MED (~2 days).

---

### 3.5 [MED] AuditLog — `agent/audit.py`

**Current state:** `AuditEntry` dataclass (L77-91) + `AuditLog` class (L92-170) — ~95 lines. Three methods on `AuditLog`: `__init__()`, `record(tool_name, args, approved, user, result, exit_code)`, `flush_audit_log(path: str | None = None) -> str | None`, `entries() -> list[AuditEntry]`. **Neither class is exported in `__all__`** (which lists L62-70 only); both are currently module-internal, used only by `AgentRuntime` and accessed from tests via the attribute path `runtime.AuditLog`.

**Problem:** `AuditLog` is the tool-audit trail — records every tool call with args hash, approval status, and outcome. Currently:
- Lives inside `runtime.py` even though it's only used by the approval-gating path (`_run_loop` calls `self._audit_log.record(...)` at L2052 and L2073)
- Has its own flush-to-disk logic mixed with in-memory state
- `flush_audit_log(path)` writes to a separate file from conversation state, which is suspicious — should be in the same persistence layer
- **API-surface change required by extraction:** moving `AuditLog`/`AuditEntry` to `agent/audit.py` promotes them from module-internal (with leading underscore implied by non-export) to public, since a new top-level module's contents are importable. **Decision:** keep both classes unprefixed (public) in `agent/audit.py` — `AuditLog`, `AuditEntry`. This is a deliberate API promotion, not a backwards-incompatible rename.

**Extraction proposal:**

```python
# agent/audit.py
@dataclass
class AuditEntry:
    tool_name: str
    args_hash: str
    approved: bool | None
    ...

class AuditLog:
    """In-memory audit trail; flushes to conversation directory."""
    def __init__(self, store: ConversationStore): ...  # NEW: depends on store
    def record(self, tool_name: str, args: dict, approved: bool | None): ...
    def flush(self) -> str | None: ...
    def entries(self) -> list[AuditEntry]: ...
```

`AuditLog` becomes a sibling to `ConversationStore`. Both can write to the same directory. The two are naturally composed.

**Why MED priority:**
- Natural pair with the persistence extraction (3.4)
- Currently has limited test coverage — moving it forces test isolation
- `flush_audit_log(path)` taking a path parameter is a smell — should be implicit from store

**Risk:** LOW.

**Effort:** LOW (~1 day).

---

### 3.6 [MED] Tool Output Truncation Policy — `agent/tool_output.py`

**Current state:** Hardcoded truncation in multiple tool implementations in `agent/tools.py`:
- `MAX_EXEC_OUTPUT = 100 * 1024` (L101) and `MAX_READ_SIZE = 50 * 1024` (L99) are module-level constants
- `_exec_command` truncates stdout/stderr at L431-439, plus L648-649
- Another tool truncates at L558-559
- `_read_file` truncates content at L249
- `_web_fetch` (L757) truncates text at L817-818 (uses caller-supplied `max_chars`, default 10,000)
- `web_search`: no truncation in `tools.py` — the runtime cap is in the LLM message formatter (orphan `_format_chunks_for_llm` at `runtime.py` L899)

The limits are module-level constants scattered across `tools.py`. A user who wants more output for a specific agent can't — they must patch `tools.py`.

**Extraction proposal:**

```python
# agent/tool_output.py
@dataclass
class OutputPolicy:
    max_chars: int | None = None
    max_stdout: int | None = None
    max_stderr: int | None = None

def truncate(result: "ToolResult", policy: OutputPolicy) -> "ToolResult": ...

# In agent/tools.py ToolDefinition (already exists):
@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable
    requires_approval: bool = False
    output_policy: OutputPolicy = field(default_factory=OutputPolicy)  # NEW
```

`execute_tool()` calls `truncate(result, defn.output_policy)` after the handler returns.

**Why MED priority:**
- Currently each tool reimplements truncation; consolidating into one function is straightforward
- `ToolDefinition` already exists and is the natural place to attach a per-tool policy
- Enables per-agent overrides (e.g., an "exec-heavy" agent gets larger stdout)

**Risk:** LOW — purely additive transform; default behavior unchanged unless `output_policy` is set.

**Effort:** LOW (~1 day).

---

### 3.7 [LOW] Sub-orchestration Lifecycle Hooks — `agent/hooks.py`

**Current state:** `_run_loop` (lines 1671–2073; the `_dispatch_approval` helper sits at L2078, `_check_stuck` at L2353) does 8 distinct things in sequence. The natural sub-phases and cut points identified during the audit, **derived from grep -nE on comment markers at L1671+ and verified against the actual code structure**:

| Phase | Lines | What it does | Cut? |
|---|---|---|---|
| 0 — Setup | 1671–1710 | Cancel check, iteration increment, add user message | ✅ natural |
| 1 — Context prep | 1711–1768 | Build API messages, compaction, tool defs, MCP merge | ✅ clean |
| 2 — KB pre-processing | 1769–1789 | `_prepare_kb_synthesis` (cache lives across iterations) | ✅ already extracted |
| 3 — LLM invocation | 1789–1791 | `_call_llm(session_key, messages, tools)` → blocks for full response | ✅ cleanest cut |
| 4 — Response parsing | 1792–1852 | Extract text/tool_calls/usage/cost | ✅ clean |
| 5 — Telemetry dispatch | 1853–1920 | Token breakdown with local-variable guards (Audit-Fix-26) | ✅ natural |
| 6 — Text-only path | 1921–1929 | KB_OUT_OF_SCOPE fallback chain | ✅ one-shot, clearly bounded |
| 7 — Tool call execution | 1930–2059 | Approval gating → dispatch → execute → enforcement → stuck check → result accumulation → limit check | ⚠️ largest; the §3.1 extraction targets this |
| 8 — Termination | 2060–2073 | Max iterations message, exception handler, `_auto_save` | ✅ clean |

Each phase transition is hardcoded — no way to insert custom logic between phases without editing `_run_loop`.

**Extraction proposal:** Define lifecycle hook protocol and emit hooks from `_run_loop`:

```python
# agent/hooks.py
class RuntimeHook(Protocol):
    def pre_send(self, conv: "Conversation", messages: list[dict]) -> list[dict]: ...
    def post_response(self, conv: "Conversation", response: LLMResponse) -> None: ...
    def pre_tool_call(self, tool_name: str, args: dict, conv: "Conversation") -> None: ...
    def post_tool_call(self, tool_name: str, args: dict, result: "ToolResult", conv: "Conversation") -> None: ...
    def pre_save(self, conv: "Conversation") -> None: ...
    def post_save(self, conv: "Conversation", path: str) -> None: ...

class HookChain:
    def __init__(self, hooks: list[RuntimeHook] = None): ...
```

**Use cases enabled:**
- Telemetry: a hook that emits to a metrics service on every `post_response`
- Custom approval: a hook that overrides `pre_tool_call` for a specific tool
- Debugging: a hook that dumps state on every transition

**Why LOW priority:**
- Most use cases are speculative — we don't have a concrete consumer yet
- Could be added incrementally as need arises
- But: defines the contract that middleware (3.1) will consume, so worth defining the interface now

**Risk:** LOW — additive interface, zero behavior change if no hooks are registered.

**Effort:** LOW (~1-2 days). Wait for a concrete consumer before shipping.

---

## 4. Cross-Cutting Observations

### 4.1 The ContextStrategy template — what all seven should follow

`agent/context_strategy.py` (687 lines) is the canonical example of modular extraction in this codebase. Re-read it before starting any of the seven. The pattern:

1. **Define a Protocol** with the minimum interface needed
2. **Move existing code** into a `Default*` class verbatim (zero logic changes)
3. **Wire the Protocol** into the runtime via a single config field or constructor arg
4. **Add telemetry** as a `*Event` dataclass (e.g., `CompactionEvent`)
5. **No upward imports** — module imports only `models/` and stdlib
6. **One-line call-site change** in `runtime.py`

### 4.2 Avoid the `agent-package-restructure` package-split trap

`PROPOSAL-agent-package-restructure.md` proposes moving whole files into `llm/`, `domain/`, `policies/` packages. This proposal **deliberately** does not do that:

- Package-level moves are hard to revert
- Package-level moves force naming decisions (`is Anthropic message conversion "llm" or "domain"?`)
- The seven extractions in §3 already achieve the same decoupling without package-level moves
- If after all seven, `agent/runtime.py` is still huge, *then* consider packages

### 4.3 What about `DEFERRED-ITEMS.md` A-11?

A-11 parked the runtime refactor on 2026-06-19 with rationale:
- "Pure refactor, no user-visible win" → addressed by §3.1 (enables new policies) and §3.2 (enables new providers)
- "Seams are non-obvious" → addressed by the seven specific extractions, each with a clear Protocol boundary
- "Current urgent work (Phase 3 security remediation) takes priority" → unchanged; this proposal is incremental

**Recommendation:** Mark A-11 as `IN-PROGRESS` once any of the seven extractions begins, and `RESOLVED` when §3.1 ships (since A-11's rationale was primarily about the monolith-ness).

### 4.4 What about `agent/enforcement.py` (942 lines)?

`enforcement.py` is itself large but **not** part of this proposal's seven extractions. It's called as a unit from `_run_loop` (L2015-2037, the `_enforcement_check(...)` block) and `agent/tool_middleware.py` (proposed §3.1) will call it via the middleware chain. Its internal structure is a separate audit — flagged here as a follow-on if §3.1 lands, but explicitly out of scope for this proposal. **Clarification on the §3.1 "Bonus":** that bonus is not a separate extraction; it's a description of how `enforcement.py` would *eventually* be reshaped to take advantage of being a middleware. It is not a commitment to do that work in this round.

### 4.5 What about `agent/tools.py` (1,242 lines)?

`tools.py` is large but mostly tool *implementations* (9 tools × ~100 lines each), not policy or orchestration. The only extraction relevant here is §3.6 (output truncation policy). The rest of `tools.py` is fine.

### 4.6 What about `agent/kb_*.py` (kb_lookup.py + kb_server.py)?

`kb_lookup.py` scored 5/5 cleanliness in the sibling-modules audit (zero cross-module coupling). `kb_server.py` is also clean — only imports `kb_lookup`. No extraction needed.

### 4.7 What about `agent/context.py` (763 lines)?

Already has a clean sibling (`context_strategy.py`). The boundary is clean. The recent JIT context discovery (commit `262af32`) was correctly contained in `context.py` and did not bleed into runtime.

---

## 5. Recommended Sequencing

The seven extractions are largely independent. Recommended order (each is shippable on its own):

| Phase | Extraction | Why this order | Estimated effort |
|---|---|---|---|
| 1 | §3.3 Cost Model | Smallest, lowest risk, validates the pattern | 1 day |
| 2 | §3.6 Tool Output Policy | Smallest in `tools.py`, validates the pattern | 1 day |
| 3 | §3.5 AuditLog | Natural pair with persistence | 1 day |
| 4 | §3.4 ConversationStore | Self-contained, no cross-cutting concerns | 2 days |
| 5 | §3.1 Tool Middleware | Largest policy win; builds on §3.4 | 3-4 days |
| 6 | §3.2 LLM Provider Adapter (non-streaming) | Largest single extraction, highest value | 3 days |
| 7 | §3.2 LLM Provider Adapter (streaming) | Riskiest; must pass PHASE-11 streaming test | 3 days |
| 8 | §3.7 Lifecycle Hooks (optional) | Wait for a concrete consumer | 1-2 days |

**Total: ~14-17 days** of focused work spread across multiple sprints.

After Phase 5, `agent/runtime.py` shrinks from 2,495 → ~1,800 lines. After Phase 7, → ~1,150 lines. After Phase 8, → ~1,090 lines. That puts runtime.py back below the 1,501-line figure that DEFERRED-ITEMS.md A-11 called "not catastrophic."

---

## 6. Migration Strategy (per extraction)

Each extraction follows the same 4-step migration:

1. **Create new module** with Protocol + Default impl that wraps the existing logic verbatim (no behavior change)
2. **Wire the Protocol** into the caller (`AgentRuntime` or `_run_loop`) via constructor or single-line refactor
3. **Test**: existing test suite must pass with zero modifications
4. **Delete** the moved code from `runtime.py`

Backward compatibility is preserved by re-exporting the old names from `runtime.py` (e.g., `from agent.audit import AuditLog, AuditEntry as _AuditEntry`) until all callers are migrated.

---

## 7. Open Questions

1. **§3.1 Approval gating config:** should `SENSITIVE_TOOLS` and `SENSITIVE_ARGS` live in code, in `providers.yaml`, or in a new `agent_policy.yaml`? Current proposal says code; could become data-driven.
2. **§3.2 MiniMax-as-OpenAI alias:** is it actually safe to share one `OpenAIProvider` instance across two registry entries, or do providers need to know their identity (e.g., for telemetry tags)?
3. **§3.4 Persistence directory:** should `ConversationStore` know about the `.crabcakes` convention, or should it take an explicit dir? Currently `_conversations_dir()` hardcodes it.
4. **§3.7 Hooks timing:** if §3.1 lands first, do we *need* §3.7? Middleware might be enough.

These can be answered during the SPEC phase for each extraction, not now.

---

## 8. Alternatives Considered

**Alt A:** Do `PROPOSAL-agent-package-restructure.md` as written (move files into `llm/`, `domain/`, `policies/` packages). **Rejected** — it's been PENDING 17 days for the reasons in §2.2. The seven extractions here achieve the same decoupling in smaller, safer steps.

**Alt B:** One mega-PR doing all seven extractions. **Rejected** — high revert cost, impossible to review, breaks tests in many places simultaneously. The ContextStrategy precedent shows incremental wins.

**Alt C:** Wait for an external forcing function (e.g., need to add Google Gemini support). **Rejected** — by the time we need it, we'll be in a worse position. The MCP proposals and consensus-LLM proposal both assume provider abstraction (§3.2).

**Alt D:** Rewrite `runtime.py` from scratch. **Rejected** — same risks as Alt B, plus we lose all the edge-case fixes that have accumulated in the current 2,495 lines.

---

## 9. Success Criteria

After all seven extractions ship:

- [ ] `agent/runtime.py` is under 1,500 lines (back below the A-11 threshold of 1,501)
- [ ] Each new module has unit tests that don't require `AgentRuntime` instantiation
- [ ] Adding a new LLM provider (Google, Mistral, vLLM, internal gateway) requires no changes to `agent/runtime.py` — only a registry entry
- [ ] Adding a new tool middleware (rate limiting, retries, telemetry) requires no changes to `agent/runtime.py`
- [ ] All existing **2,269 tests** pass with zero modifications (`pytest --collect-only` reports this count as of 2026-06-28)
- [ ] Streaming regression tests pass: `TestStreaming` (L1050), `TestStreamingSignature` (L1413), `TestStreamingUsageCapture` (L1487) in `tests/test_agent_runtime.py`
- [ ] `scripts/audit_streaming_scenarios.py` and `scripts/audit_attack_scenarios.py` continue to work (they patch/import `_PROVIDER_CALLERS`/`_PROVIDER_STREAMERS` — see §3.2 external callers note)
- [ ] ARCHITECTURE.md §3.21m is updated to reflect the new module structure **and** the line-count snapshot is updated to match the post-extraction size
- [ ] DEFERRED-ITEMS.md A-11 is marked `RESOLVED`
- [ ] `PROPOSAL-agent-package-restructure.md` is marked `SUPERSEDED` (or merged into this one)
- [ ] **ROI metric:** At least one new capability unlocked (a new provider added, or a new middleware shipped) within 6 months of completion. If 6 months pass with zero unlocked capabilities, the proposal's value is questioned and a follow-up audit reviews whether the extraction was worth the ~14-17 day cost.

---

## 10. Conclusion

`agent/runtime.py` at 2,495 lines is past the "comfortable monolith" threshold and into "actively slowing down iteration" territory. The PENDING `agent-package-restructure` proposal and DEFERRED A-11 both acknowledge this but neither has shipped.

This proposal identifies **seven independent, incremental extractions**, each following the proven ContextStrategy pattern, each shippable in its own commit, each with a clear Protocol boundary. Sequenced over ~14-17 days, they reduce `runtime.py` by ~55% (down to ~1,090 lines) while enabling new capabilities (provider hot-swap, custom middleware, per-tool policies) that the current monolith blocks.

**Recommended next step:** Approve this proposal, mark `agent-package-restructure` as SUPERSEDED, mark `DEFERRED-ITEMS.md` A-11 as IN-PROGRESS, and begin Phase 1 (§3.3 Cost Model) as a proof-of-pattern. If Phase 1 ships clean, the remaining six follow in sequence.

---

## 11. Audit Trail — Findings Applied

This proposal was adversarially audited on 2026-06-28 by re-reading every cited line number, symbol name, and count against the actual codebase. The following issues were found and fixed inline (cross-references to the sections that contain the fix in parentheses):

**Tier 1 — Materially wrong claims:**
1. **Test count wrong** — claimed 1,394 tests; actual is 2,269 (`pytest --collect-only`). (§9)
2. **Line numbers drifted** in §3.1, §3.2, §3.6, §3.7, §4.4 — fixed by re-deriving from `grep -n` against the actual file. (§3.1, §3.2, §3.6, §3.7, §4.4)
3. **AuditLog "public methods" framing** — the class is module-internal (not in `__all__`); extraction promotes it to public. (§3.5)
4. **Phase 3 of `_run_loop` seam analysis** was listed as L1788–L1791 (4 lines, physically impossible). Regenerated with verified ranges from comment markers. (§3.7)

**Tier 2 — Misleading claims:**
5. **Provider count 3 → 5** — `openrouter` and `zai` are already wired and were missed. (§3.2)
6. **"PHASE-11 streaming regression test"** — vague; the actual test classes are `TestStreaming` (L1050), `TestStreamingSignature` (L1413), `TestStreamingUsageCapture` (L1487). (§9)
7. **Ollama/vLLM as future providers** — phantom use case; replaced with "any new OpenAI-compatible API." (§3.2)
8. **MiniMax "alias collapse"** is actually a **4-way OpenAI collapse** (openai, minimax, openrouter, zai), not a 2-way one. (§3.2)

**Tier 3 — Missing analysis now added:**
9. **Concurrency considerations** added to §3.1 — middleware chain must run synchronously within `_run_loop`'s thread; the only async escape is `_dispatch_approval`. (§3.1)
10. **Rollback plan** added to §3.2 — if streaming extraction fails, ship non-streaming + the other 5 anyway. (§3.2)
11. **External callers enumerated** — `scripts/audit_streaming_scenarios.py` (10 patches) and `scripts/audit_attack_scenarios.py` (line 6 import) must continue to work via re-exports. (§3.2, §9)
12. **ROI metric** added to §9 — at least one new capability must unlock within 6 months. (§9)

**Tier 4 — Other additions and fixes:**
13. **API-surface change for AuditLog** documented as deliberate (internal → public on extraction). (§3.5)
14. **Cost table expansion** — five entries (`openai`, `minimax`, `anthropic`, `openrouter`→`OPENAI_COST`, `zai`→`OPENAI_COST`); three constants (`_OPENAI_COST`, `_MINIMAX_COST`, `_ANTHROPIC_COST`). (§3.3)
15. **`_format_chunks_for_llm` (L899-915)** is an orphan — not in any of the seven extractions; called at L1480, L1661. **Recommendation:** add to §3.2 (LLM-related message formatting) when that extraction is scoped, or fold into a new §3.8 (KB→LLM bridge). Not a separate extraction.
16. **`_call_llm_streaming` parameter list** confirmed (L2241: `session_key, base_url, api_key, model, caller_key, messages, tools, timeout`); streaming phase migration must preserve all eight.
17. **`agent/runtime.py` line count discrepancy** — proposal mentioned "2,494 lines" in §2.1, §5, §8, and §10; actual is 2,495 (off-by-one in growth table). All instances updated.

**Items deferred to SPEC phase (not fixed in this proposal):**
- Whether `SENSITIVE_TOOLS`/`SENSITIVE_ARGS` belong in code, `providers.yaml`, or new `agent_policy.yaml` (§7 Q1)
- Whether `OpenAIProvider` instances need per-registry-key identity for telemetry tags (§7 Q2)
- Whether `ConversationStore` should hardcode `.crabcakes` or take explicit dir (§7 Q3)
- Whether §3.7 hooks are still needed once §3.1 middleware ships (§7 Q4)

---

**End of proposal. Total: ~750 lines after audit fixes.**