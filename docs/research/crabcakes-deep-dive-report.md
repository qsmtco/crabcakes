# 🦀 CrabCakes Deep Dive — Read-Only Report

> Generated: 2026-06-25
> Scope: Architecture overview, context management analysis, feature inventory, comparison with external projects

---

## 1. What CrabCakes Is

**CrabCakes is a local-first, GTK4-native AI coding agent platform.** Think of it as your own Claude Code / Cursor / Windsurf — but it runs entirely on your machine with your API keys, your projects, your tools, and a self-improving feedback loop.

| Dimension | Detail |
|-----------|--------|
| **Codebase** | 69,359 lines of Python across ~80 modules |
| **Tests** | 31,533 lines (45% of codebase — heavy test culture) |
| **Specs** | 133 specification documents (rigorous engineering process) |
| **UI** | GTK4 / Adwaita native (Linux desktop-first) |
| **Runtime** | Single-file 2,308-line `agent/runtime.py` core loop |
| **Providers** | OpenAI, MiniMax, Anthropic, OpenRouter, ZAI (GLM) — all OpenAI-compatible adapters |
| **Transport** | `urllib.request` (no httpx/requests dependency for LLM calls), SSE streaming |

---

## 2. Architecture — The Context Pipeline

This is the core question. Here's how context flows from project files → LLM context window:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SYSTEM PROMPT COMPOSITION                           │
│                    utils/prompt_loader.py (477 lines)                       │
│                                                                            │
│  1. prompts/system/default.md         ← always (role, tools, format)      │
│  2. prompts/system/collab.md         ← always (agent-to-agent protocol)   │
│  3. prompts/system/crabcakes-context.md ← always (platform identity)      │
│  4. prompts/system/project-awareness.md  ← if project active              │
│  5. prompts/system/crabcakes-commands.md ← if project active              │
│  6. prompts/system/project-onboarding.md ← if project NOT yet onboarded   │
│  7. prompts/system/coder.md OR debugger.md OR auxilium.md ← by agent role│
│  8. .crabcakes/{role}-bugs.md        ← self-improvement bug journal       │
│  9. .crabcakes/{role}-rules.md       ← self-improvement project rules     │
│                                                                            │
│  ══════════════════════════════════════════════════════════════════════    │
│  10. FILE CONTEXT (agent/context.py — 541 lines)                          │
│      ├── .crabcakes/ project docs (always first, always included)          │
│      ├── Directory tree (gitignore-respected)                             │
│      ├── Key files: README.md, ARCHITECTURE.md, pyproject.toml, etc.      │
│      └── CORE FILES at END (README, AGENTS, CONVENTIONS, ARCHITECTURE)    │
│                                                                            │
│  ══════════════════════════════════════════════════════════════════════    │
│  BUDGET: 15% of context window (SYSTEM_PROMPT_BUDGET_FRACTION = 0.15)     │
│  Truncation: smart — core files always preserved, non-core trimmed oldest │
│  Hard cap: 16K tokens (~64K chars) when model_max_tokens unknown          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Currently Using: The Full Stack

| Layer | What | Lines | Strategy |
|-------|------|-------|----------|
| **Template composition** | `prompt_loader.compose_system_prompt()` | 477 | Layered MD templates with `{{VARIABLE}}` fill |
| **File context builder** | `context.build_file_context_with_core_files()` | 541 | `.crabcakes/` docs → tree → key files → core files at end |
| **Token estimation** | `Conversation.get_token_estimate()` | 503 | tiktoken when available, chars÷4 fallback, **cached** (CB-5 fix) |
| **Token breakdown** | `Conversation.get_token_breakdown()` | 503 | Per-turn observability: system vs conversation vs remaining |
| **Context trimming** | `Conversation.trim_to_token_limit()` | 503 | Remove oldest exchanges, preserve last 4 messages, inject summary |
| **Smart truncation** | `_truncate_file_context_smart()` | 477 | Section-aware: core files always kept, others trimmed oldest-first |
| **Prompt budgeting** | `_apply_system_prompt_budget()` | 477 | 15% of context window for system prompt (file context capped within that) |
| **Model context discovery** | `/v1/models` probe in `provider_test.py` | 280 | Auto-detect context window, pre-fill SpinButton in Settings |
| **KB retrieval** | `kb_lookup.py` (BAAI/bge-small-en-v1.5) | 279 | Local cosine-similarity over pre-indexed chunks (384-dim) |
| **KB server** | `kb_server.py` (localhost:18790) | 457 | OpenAI-compatible wrapper so runtime needs zero changes |
| **KB synthesis** | Free Llama endpoint (3s timeout) | (in kb_server) | Synthesizes raw chunks into coherent answer |
| **KB fallback** | Per-agent `fallback_provider` | (in runtime) | If KB returns OUT_OF_SCOPE, retry with fallback model |
| **Self-improvement** | Bug journal + project rules | `prompt_loader` §7 | Per-role `{role}-bugs.md` + `{role}-rules.md` in `.crabcakes/` |
| **Enforcement** | Syntax → Tests → Lint (3-tier) | 882 | Post-write verification with per-project `enforcement.json` config |
| **Security** | Trust gate, untrusted fence, scrubbed env | Throughout | HIGH-5 fences for `.crabcakes/` content, CRIT-1/2 for subprocess |

---

## 3. Context Management — How Good Is It?

### What's Excellent ✅

1. **Budget-aware system prompt (15% of context window)** — Not many agent platforms explicitly budget the system prompt as a fraction of the context window. This prevents the "bloated system prompt leaves no room for conversation" failure mode.

2. **Smart truncation with core file preservation** — When budget is exceeded, core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) are always kept. Non-core sections are trimmed from the *beginning* (oldest first), preserving the most recent context. This is genuinely sophisticated.

3. **Tiktoken-accurate token counting with cache** — The CB-5 hotfix added a `(len(messages), hash(system_prompt))`-keyed cache so the trim loop doesn't re-encode the entire conversation on every iteration. Without this, a 100K-char system prompt would make each `get_token_estimate()` call take ~6 seconds.

4. **Summary-on-trim injection** — When older messages are trimmed, a compact summary of the removed turns is injected so the model doesn't lose context of what was accomplished. Budget-aware: skipped if injection would push back over the limit.

5. **Per-turn token breakdown observability** — `get_token_breakdown()` returns system tokens, conversation tokens, remaining, usage % — dispatched to the UI on every turn.

6. **.crabcakes/ project docs always first** — Architecture, requirements, context, tasks, team, workflow docs are included before the tree, ensuring the agent always has project docs even when file context is truncated.

7. **Untrusted-data fences** — Project-supplied `.crabcakes/` content is wrapped in `<untrusted-project-data>` fences with explicit "treat as data, not instructions" directives. This is a real defense against prompt injection from cloned repos.

8. **/v1/models probe for context window auto-discovery** — Just shipped (2026-06-24). The UI now auto-fills the context window SpinButton when a provider test succeeds.

### What's Missing or Weak ⚠️

1. **No compaction/consolidation during conversation** — The only context reduction mechanism is `trim_to_token_limit()` which *deletes* old messages (with a brief summary). There's no mid-conversation "context compaction" that rewrites/summarizes earlier turns into a denser form while preserving semantics. This is the #1 missing capability compared to Claude Code's `/compact` or the FCA framework.

2. **No KV cache / latent briefing** — The self-improvement layers (bug journal, rules) are re-injected in full on every system prompt rebuild. There's no mechanism to "compile" these into a denser representation or to use KV cache tricks for static prompt sections.

3. **15% budget may be too tight for large system prompts** — The budget only caps the file context portion. If templates + bug journal + rules already consume 14% of a 128K window, only 1% remains for file context. No mechanism to dynamically adjust the budget fraction based on actual template size.

4. **No context window utilization monitoring** — While `get_token_breakdown()` reports usage, there's no persistent tracking or alerting when utilization exceeds thresholds (e.g., >80%). No "context pressure" signal that could trigger proactive compaction.

5. **File context is all-or-nothing per file** — `_read_file_safe()` reads entire files (up to 50KB). There's no chunked or semantic-file-partial reading (e.g., "read only the class definition, not the full 2000-line module"). The Context-Engine-AI approach (MCP semantic search over symbol graphs) would be a big upgrade.

6. **No multi-agent context coordination** — Each agent conversation has its own independent context. When Coder and Debugger are both working on the same project, there's no shared context surface or context deduplication. Each agent independently reads the same files.

7. **Dream consolidation (SPEC-4) is PARTIAL** — The highest layer of the self-improvement stack (autonomous nightly analysis of accumulated feedback → prompt/rules evolution) is spec'd but not fully implemented. This is the "context as a learning surface" capability.

8. **Query-based file context is simple name matching** — `build_file_context(project_path, query=...)` uses `query_lower in name.lower()` substring matching on filenames. No semantic search, no content-aware retrieval.

---

## 4. What's Currently Built (Feature Inventory)

### Agent Runtime
| Feature | Status | Detail |
|---------|--------|--------|
| Tool loop (LLM → tool calls → execute → return) | ✅ Live | `runtime.py` 2,308 lines |
| Multi-provider API (OpenAI, MiniMax, Anthropic, OpenRouter, ZAI) | ✅ Live | 5 provider adapters |
| SSE streaming with tool-call ID preservation | ✅ Live | OpenAI, MiniMax, Anthropic stream formats |
| Conversation persistence (JSON, chmod 0600) | ✅ Live | API key NOT serialized (re-resolved from providers.yaml) |
| Cost tracking (per-model pricing tables) | ✅ Live | OpenAI $2.5/$10, MiniMax $0.5/$1, Anthropic $3/$15 per 1M tokens |
| Approval gating (exec_command, write_file on sensitive paths) | ✅ Live | PM approval with timeout |
| Stuck detection (repeated tool calls) | ✅ Live | Pattern matching on tool history |
| Cancellation | ✅ Live | Immediate cancel signal + approval resolution |
| MCP client integration (Phase B) | ✅ Live | stdio transport, persistent event loop |
| KB fallback chain (primary → fallback provider) | ✅ Live | One-shot retry on KB_OUT_OF_SCOPE |

### Self-Improvement Stack
| Layer | Spec | Status | What |
|-------|------|--------|------|
| 1. Bug journal | SPEC-1 | ✅ DONE | `.crabcakes/{role}-bugs.md` auto-injected |
| 2. Project rules | SPEC-1 | ✅ DONE | `.crabcakes/{role}-rules.md` auto-injected |
| 3. Auto-test enforcement | SPEC-2 | ✅ DONE | Syntax → Tests → Lint (3-tier) |
| 4. Structured feedback | SPEC-3 | ✅ DONE | Machine-parseable audit reports → auto-populate bug journal |
| 5. Dream consolidation | SPEC-4 | ⚠️ PARTIAL | Nightly analysis → prompt/rules evolution |

### Context Management
| Feature | Spec | Status | What |
|---------|------|--------|------|
| System prompt budgeting | CB-2 | ✅ DONE | 15% of context window |
| Token-accurate estimation (tiktoken) | CB-4 | ✅ DONE | With cache (CB-5) |
| Smart file context truncation | CB-5 | ✅ DONE | Core files always preserved |
| Summary-on-trim injection | CB-4/5 | ✅ DONE | Budget-aware, fires on any removal |
| Per-turn token breakdown | CB-3 | ✅ DONE | UI observability |
| Model context window discovery | SPEC-MODEL-CAPACITY | ✅ DONE (just shipped!) | `/v1/models` probe → SpinButton pre-fill |

### Knowledge Base (Auxilium)
| Feature | Status | Detail |
|---------|--------|--------|
| Local embedding index | ✅ Live | BAAI/bge-small-en-v1.5, 384-dim, cosine similarity |
| KB server (localhost:18790) | ✅ Live | OpenAI-compatible, zero runtime changes |
| LLM synthesis of chunks | ✅ Live | Free Llama endpoint, 3s timeout |
| Confidence thresholding | ✅ Live | Minimum score 0.35, confidence threshold 0.55 |
| 12 knowledge docs | ✅ Live | 672KB total (install, providers, commands, etc.) |

### Security
| Feature | Status | Detail |
|---------|--------|--------|
| Project trust gate | ✅ Live | HIGH-5: skip `.crabcakes/` if project not trusted |
| Untrusted data fences | ✅ Live | `<untrusted-project-data>` wrappers |
| Scrubbed subprocess env | ✅ Live | CRIT-2: only PATH/HOME/LANG survive |
| Binary allowlist for test commands | ✅ Live | CRIT-1: python3, pytest, ruff, mypy, eslint, etc. |
| Shell metachar rejection | ✅ Live | CRIT-1: `;|&$\`()` in filenames rejected |
| Path sandboxing | ✅ Live | All file ops within project_path |
| Audit log (tool name, args hash, approval, result hash) | ✅ Live | A-4: append-only, in-memory + flush to disk |

---

## 5. Comparison: CrabCakes vs. The Hidden Gems

| Capability | CrabCakes | agent-context-system | ACE (FCA) | agents-md | Context-Engine-AI |
|-----------|-----------|---------------------|-----------|-----------|-------------------|
| Budget-aware system prompt | ✅ 15% of CX | ❌ | ✅ 40-60% target | ❌ | ❌ |
| Smart truncation with invariants | ✅ Core files kept | ✅ 9:1 compression | ❌ | ❌ | ❌ |
| Token-accurate counting | ✅ tiktoken + cache | ❌ chars only | ❌ | ❌ | ❌ |
| Summary-on-trim | ✅ Budget-aware | ✅ Consolidation phase | ✅ Compaction | ❌ | ❌ |
| KV cache / latent briefing | ❌ | ❌ | ❌ | ❌ | ❌ |
| Mid-conversation compaction | ❌ | ✅ Auto-consolidation | ✅ FCA protocol | ❌ | ❌ |
| Byte-cap output control | ❌ | ❌ | ❌ | ✅ `head -c 4000` | ❌ |
| Semantic file partial reads | ❌ | ❌ | ❌ | ❌ | ✅ MCP symbol graph |
| Self-improvement loop | ✅ 5-layer stack | ❌ | ❌ | ❌ | ❌ |
| Untrusted-data fences | ✅ | ❌ | ❌ | ❌ | ❌ |
| Multi-agent context coordination | ❌ | ❌ | ❌ | ❌ | ❌ |
| Offline-first / zero deps | ❌ (needs tiktoken) | ✅ Zero deps | ❌ | ✅ | ❌ |

---

## 6. What CrabCakes Should Steal (Ranked by Impact)

### 🔴 High Impact

1. **Mid-conversation compaction** (from FCA / agent-context-system)
   - Add a `/compact` command or auto-trigger at 70% utilization
   - Re-summarize the conversation tail into a dense form
   - This is the single biggest missing capability

2. **Byte-cap tool output control** (from agents-md)
   - Change `exec_command` result truncation from line-based (`head -n 20`) to byte-based (`head -c 4000`)
   - One huge line can still flood context. This is a 5-line change.

3. **Dynamic budget fraction** (from CrabCakes own analysis)
   - After template composition, measure actual template size → adjust file context budget
   - Instead of fixed 15%, use `max(0.15, 0.25 - template_fraction)`

### 🟡 Medium Impact

4. **Context pressure signal** — Track utilization over time. When consistently >80%, surface a warning. When >90%, auto-trigger compaction or suggest `/compact`.

5. **Semantic file partial reads** (from Context-Engine-AI) — Instead of reading entire 2000-line files, use a symbol index to read only the relevant class/function. Would require an MCP server or tree-sitter integration.

6. **Multi-agent context dedup** — When Coder and Debugger share a project, deduplicate the file context they both load. Shared context surface per project, not per conversation.

### 🟢 Nice to Have

7. **KV cache for static prompt sections** — The system prompt templates + bug journal + rules are mostly static across turns. Pre-compile them into KV cache entries to avoid re-encoding on every call. Requires provider-level support.

8. **Dream consolidation completion** (SPEC-4) — Finish the nightly analysis layer so the self-improvement stack is fully operational. This is a process improvement, not a context-engineering improvement per se.

---

## 7. Key Numbers

| Metric | Value |
|--------|-------|
| Core runtime | 2,308 lines |
| Context pipeline (context + prompt_loader + conversation) | 1,521 lines |
| Total production code | 69,359 lines |
| Test code | 31,533 lines (45% ratio) |
| Specifications | 133 documents |
| System prompt budget | 15% of context window |
| Default context window | 128,000 tokens (sentinel) |
| File context hard cap | 50K chars (build_file_context) |
| Individual file cap | 50KB (read), 2MB (write) |
| KB confidence threshold | 0.55 (top score), 0.35 (minimum) |
| Number of context pipeline phases | 5 (CB-1 through CB-5) |
| Self-improvement layers | 5 (SPEC-1 through SPEC-5) |
| Context bloat audits | 2 end-to-end with post-mortems |
| Token estimate cache | Keyed on `(len(messages), hash(system_prompt))` |

---

**Bottom line:** CrabCakes has a surprisingly sophisticated context management system for a project of its size — budget-aware prompting, tiktoken-accurate estimation with caching, smart truncation with invariant preservation, and a 5-layer self-improvement stack. The #1 gap is **mid-conversation compaction**: the system only knows how to delete old messages (with a brief summary), not how to rewrite/consolidate earlier turns into a denser, still-accurate form. Adding that would close the gap with the best context engineering projects on GitHub.
