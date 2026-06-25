# Crabcakes Context Management: Frontier Strategies Worth Incorporating

*Synthesis of three deep research surveys (academic, production, novel techniques) filtered against crabcakes' architecture. June 25, 2026.*

---

## Read this first

The just-shipped **SPEC-CONTEXT-MANAGEMENT-ROADMAP** (Phases P1–P7) already brings crabcakes to parity with the best open-source agents (Cline, OpenCode, OpenHands, Aider). This document goes **beyond** that spec — it identifies what crabcakes could *next* adopt from the 2026 frontier, organized by implementation effort and novelty.

Every recommendation below was filtered through three constraints:
1. **Single-process agent runtime** — no model retraining, no CUDA kernels
2. **Pure-data `models/conversation.py`** — stdlib only, no GTK/network/LLM calls
3. **CB-6 tool-call pairing invariant** — must be preserved

---

## Tier 1 — High-impact, low-effort additions (post-SPEC roadmap)

### T1.1 — Recursive hierarchical summarization
**Source:** Wang et al., [arXiv:2308.15022](https://arxiv.org/abs/2308.15022); Anthropic "context engineering" cookbook; Letta/MemGPT
**Status:** Spec P5 has a single-level summary. Recursion is a strict superset.
**Effort:** Low. Pure prompt engineering + existing `_fit_summary`.

**What:** When the conversation exceeds a "summary threshold" (e.g., 3 summaries generated), summarize *the summaries* into a "layer-2" recap. Each new user turn generates a fresh leaf summary; periodic background consolidation rolls them up.

**Why it's novel:** Current spec replaces the entire history with one growing summary. Recursion creates **stratified memory** — coarse at the top (whole-session arc), fine at the leaves (recent exchanges). Anthropic's "structured notes / STATE.json" pattern is exactly this; Letta's recall-memory compaction is a production instance.

**Implementation sketch:**
```python
# In Conversation:
self._summary_layers: list[str] = []  # L0 = oldest, L_n = newest

def _maybe_rollup(self, threshold: int = 3) -> None:
    if len(self._summary_layers) >= threshold:
        oldest = self._summary_layers.pop(0)
        next_oldest = self._summary_layers.pop(0)
        self._summary_layers.insert(0, self._summarize_pair(oldest, next_oldest))
```
- Pure data, no LLM calls in `models/conversation.py`
- LLM call lives in `agent/runtime.py` (orchestrator), preserving layering rules
- Threshold and rollup policy live in a new `SummaryRollupPolicy` dataclass

**Evidence:** Wang et al. show hierarchical summarization consistently beats full-context and single-level summarization on long-horizon dialogue. Mem0 production reports 91% latency reduction partly from stratified retrieval (Mem0g graph layer).

---

### T1.2 — Structured summary schemas (PRISM-inspired)
**Source:** [arXiv:2412.18914](https://arxiv.org/abs/2412.18914) PRISM (EMNLP 2025/ICLR 2026)
**Status:** Spec P5 generates free-text summary. Structured is strictly more queryable.
**Effort:** Low. Replaces the summary string with a dict-shaped message.

**What:** Instead of `_last_exchange_summary()` returning a free-text recap, return a **structured schema**:
```python
class ConversationDigest:
    arc: str              # one-line overall arc
    decisions: list[str]  # things that were decided
    constraints: list[str]  # constraints the agent operates under
    open_questions: list[str]
    referenced_paths: list[str]  # files / symbols touched
    token_estimate: int
```
Serialize as `Message(role="assistant", content=json.dumps(...), is_summary=True)`.

**Why it's novel:** Free-text summaries lose the "searchability" that an agent could use to remember *what was decided* vs *what was discussed*. PRISM's core insight is that **code-as-memory** is more reliable than text-as-memory — the structured form lets the LLM later recall specific decisions when reasoning about new turns. This is also Mem0's `FactExtractionMemoryBlock` pattern (LlamaIndex) applied to in-conversation memory.

**Implementation:**
- Add `ConversationDigest` dataclass in `models/conversation.py` (stdlib only — `dataclasses` + `json`)
- Change `_last_exchange_summary()` signature to return `ConversationDigest | None`
- Runtime (`agent/runtime.py`) serializes to JSON before injection

**Evidence:** PRISM achieves 4× shorter contexts while *outperforming* baselines — code-structured memory is denser than text summaries. LlamaIndex's `FactExtractionMemoryBlock` is the production proof that structured memory beats flat text for retrieval.

---

### T1.3 — File-path offloading for large tool outputs (Anthropic "tool clearing")
**Source:** [Anthropic Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); LangChain Deep Agents "Write" primitive
**Status:** Spec P4 stubs oversized tool outputs to 200 chars + flag. Offload is a strict superset.
**Effort:** Low. Existing `prune_tool_outputs()` gets a new mode.

**What:** When a tool result exceeds (e.g.) 5,000 chars, **write it to disk** (e.g., `.crabcakes/tool-outputs/{conv_id}/{msg_id}.txt`) and replace the in-context content with a path + 200-char preview + a `tool_read_path` stub.

```python
@dataclass
class OffloadedToolResult:
    path: str              # relative path from project root
    preview: str           # first 200 chars
    byte_count: int
    truncated: bool = True
```

When the agent needs the full content, it calls a built-in `tool_read_path(path)` tool. The pointer stays in context; the bulk lives on disk.

**Why it's novel:** Spec P4 is **lossy** — once stubbed, the data is gone. Offload is **lossless** — re-fetchable on demand. Anthropic's Claude Code uses exactly this pattern for repo files. LangChain Deep Agents formalizes it as the "Write" primitive.

**Implementation:**
- Add `OffloadedToolResult` dataclass
- Extend `prune_tool_outputs()` with `mode: Literal["stub", "offload"]`
- Add `tool_read_path` tool entry to `default.md` tool list
- Wire into `agent/runtime.py` tool execution loop

**Evidence:** Anthropic reports up to 54% improvement on agent benchmarks from context engineering alone, with tool-result clearing as the highest-ROI tactic. Cursor's context engineering plugin ranks tool-output offload as the #1 priority for compression.

---

### T1.4 — Just-in-time retrieval over preloading (LangChain "Select")
**Source:** LangChain "Write/Select/Compress/Isolate" framework; Anthropic just-in-time retrieval
**Status:** Crabcakes currently always dumps the full file context. JIT is a paradigm shift.
**Effort:** Medium. Touches `agent/context.py` and a new tool.

**What:** Instead of preloading `agent/context.py`'s 50K-char file context, store the file list in context and **let the agent pull files via tool call** when needed:
```python
context_in_prompt = "[File index: 142 files, ~50K chars. Call file_search('symbol') to retrieve.]"
```
Built-in tools: `file_search(query)`, `file_read(path)`, `directory_tree(path)`.

**Why it's novel:** "Just-in-time retrieval" is the most-cited 2026 pattern from Anthropic, LangChain, and Letta. Crabcakes currently violates it by stuffing 50K chars of file context up front, even when the user's question is about something else entirely. RAG over conversation history is the production consensus (LlamaIndex blocks, Mem0, Zep all do it).

**Implementation:**
- Add `JITContextIndex` class in `agent/context.py` that lists file paths + summaries + byte counts
- Modify `build_file_context_with_core_files()` to accept `jit: bool = False`
- Add `file_search`/`file_read` tools to `default.md`
- Add metrics: tokens-saved-per-turn via JIT vs preload

**Trade-off:** Adds tool-call latency (turn latency goes up, total tokens go down). Default to preload for short sessions, JIT for long ones.

**Evidence:** LangChain benchmarks show ~30% token reduction with negligible quality loss when using Select for stable, large contexts. Anthropic's Claude Code used the JIT pattern to handle entire codebases.

---

### T1.5 — Per-tool retention policy (OpenCode `PRUNE_PROTECTED_TOOLS`)
**Source:** OpenCode `prune()`; production agent research in `hidden-gems-agent-context-management.md`
**Status:** Spec P4 prunes all tool outputs equally. Per-tool is finer-grained.
**Effort:** Low. Adds a config knob.

**What:** Different tools have different "post-use value":
- `read_file`, `exec_command` output is **largely forgotten** after the next agent turn uses it
- `web_search` results may stay relevant for several turns
- `memory_read` outputs may stay relevant for the whole session

```python
@dataclass
class ToolRetentionPolicy:
    default_turns_to_keep: int = 1     # stub after 1 turn past last use
    per_tool: dict[str, int] = field(default_factory=lambda: {
        "web_search": 5,
        "memory_read": 999,
        "file_search": 3,
        "read_file": 1,
        "exec_command": 1,
    })
```

**Why it's novel:** Spec P4's `prune_tool_outputs(soft)` treats all tool outputs equally. Real conversations have wildly different tool value profiles. OpenCode's `PRUNE_PROTECTED_TOOLS` list was the highest-impact "hidden gem" finding from crabcakes' own research.

**Implementation:**
- Add `ToolRetentionPolicy` to `models/conversation.py` (or `agent/config.py` — config knob)
- Modify `prune_tool_outputs()` to accept the policy and skip protected tools
- Add `last_used_turn_idx` tracking on tool result messages

**Evidence:** OpenCode's research (crabcakes' own `hidden-gems-agent-context-management.md`) showed that protecting just 3 critical tools reduced agent errors by 40% in long sessions.

---

## Tier 2 — Architecturally novel, medium effort

### T2.1 — Conversation checkpointing ("time-travel debugging")
**Source:** Letta MemFS (git-tracked filesystem memory); industry pattern of `STATE.json` checkpoints (Anthropic)
**Status:** No equivalent in crabcakes or spec.
**Effort:** Medium.

**What:** Allow the user (and the agent) to **snapshot the conversation** at named points and **rewind/restore**:
```python
conv.create_checkpoint(name="after-decision-A")
# ... many turns later ...
conv.restore_checkpoint("after-decision-A")  # restores messages + is_summary flags
```
Checkpoints are git-trackable if the user enables it (use the same `.crabcakes/` directory pattern).

**Why it's novel:** Every major framework (Letta, Mem0, LangGraph) exposes checkpointing, but crabcakes doesn't. It's particularly valuable for **debugging agent behavior** ("what did the agent know when it made decision X?") and for **user-controlled "undo"** of unwanted exploration.

**Implementation:**
- Add `ConversationCheckpoint` dataclass: `name`, `created_at`, `messages_snapshot`, `summary_layers_snapshot`, `digest_snapshot`
- Add `create_checkpoint()`, `restore_checkpoint()`, `list_checkpoints()` methods on `Conversation`
- Optional: serialize as JSON in `.crabcakes/checkpoints/{conv_id}/`

**Evidence:** LangGraph's `MemorySaver` is the production proof — every LangGraph deployment has checkpointing enabled by default. Letta's MemFS system extends this with git semantics for diff/rollback.

---

### T2.2 — Dream consolidation as background task (ChatGPT "dreaming" + SPEC-4)
**Source:** [OpenAI dreaming announcement](https://openai.com/index/chatgpt-memory-dreaming/); crabcakes' own SPEC-4 (already partial)
**Status:** SPEC-4 mentions nightly dream consolidation. No implementation in this scope.
**Effort:** Medium-High (cross-cutting).

**What:** Periodically (e.g., between sessions or every N turns in long sessions), run a **synthesis pass** that:
1. Reads all session digests (T1.2)
2. Identifies recurring patterns, preferences, project facts
3. Writes structured "dreams" to `.crabcakes/dreams/{user_id}.jsonl`
4. These dreams get injected into the system prompt as a `<agent-memory>` block

**Why it's novel:** ChatGPT's "dreaming" is the most distinctive production memory feature of 2025–2026 — a background process that synthesizes memory across conversations, analogous to human memory consolidation during sleep. Anthropic's "structured notes for cross-session continuity" is the same idea.

**Implementation:**
- New module: `agent/dreaming.py`
- Hooks: end-of-session, start-of-session, every-N-turns-in-long-session
- Storage: `.crabcakes/dreams/{user_id}/{session_id}.jsonl` (append-only, git-friendly)
- New prompt section: `<agent-memory>` populated from dream consolidation

**Trade-off:** Adds latency between sessions (user-visible). Need a "skip dreaming" config for low-latency requirements.

**Evidence:** OpenAI reports this is the source of ChatGPT's most distinctive "feels like it knows me" quality. Anthropic uses identical pattern in Memory Tool.

---

### T2.3 — Token-eviction awareness via cache-aware pruning
**Source:** H2O, SnapKV, FastGen (ICLR 2024 / NeurIPS 2023); L2-Norm eviction (EMNLP 2024)
**Status:** Spec doesn't touch KV-cache behavior. Frontier research is at model inference level — but crabcakes can approximate.
**Effort:** Medium. New signal in the runtime.

**What:** While crabcakes can't evict KV cache entries (that's the model provider's job), it can **structure prompts to match how attention decays**. Two implementations:

**a) Position-aware reordering:** Place critical messages (system, recent, last user turn, last assistant action) at the **start and end** of the context — the positions where attention is highest. Move stale tool outputs to the middle.

**b) Importance-weighted summarization:** When generating a summary, score each message by "likely future relevance" (e.g., does this message contain a decision, constraint, or referenced path?). Spend more summary tokens on high-importance messages.

```python
@dataclass
class MessageImportance:
    msg_id: int
    score: float                # 0.0–1.0
    reasons: list[str]          # "decision", "constraint", "file_reference", "tool_output_used"
```

**Why it's novel:** This brings **academic attention-mechanics** into a **runtime decision**. Anthropic's "place critical info at beginning or end" cookbook rule, Letta's memory placement heuristics, and the FastGen finding that "some heads attend to specific tokens globally" all point to the same principle: **position matters as much as content**.

**Implementation:**
- Add `MessageImportance` scoring to `models/conversation.py`
- Optional: heuristic scorer (no LLM call) for fast path; LLM-based scorer for critical conversations
- Reorder `messages` before sending to provider (keeping chronological ordering tag in metadata)

**Evidence:** Anthropic and Cursor both cite "place critical info at edges" as a top-3 context engineering tactic. FastGen shows that even at the model level, position-aware eviction is the dominant strategy.

---

### T2.4 — Semantic "conversation spine" extraction
**Source:** Novel synthesis from Anthropic "structured notes"; crabcakes' SPEC-4 dreaming
**Status:** No existing system implements this exactly.
**Effort:** Medium-High.

**What:** During compaction (T1.1 rollup), extract the **spine** of the conversation — a short list of pivotal moments:
```python
@dataclass
class ConversationSpine:
    task: str                   # original task
    key_decisions: list[Decision]
    dead_ends: list[str]        # approaches tried and abandoned
    state_mutations: list[StateChange]
    open_loops: list[str]       # "TODO: verify X", "user wants Y"
```

The spine is **always** in the prompt (when the conversation is long enough to need it), alongside system prompt and recent messages. It survives compaction. It's the agent's persistent "self-model" of what it's doing.

**Why it's novel:** Most systems preserve system prompt + recent messages. The middle (the "arc" of the work) is precisely what gets lost in summarization. Anthropic's structured notes pattern preserves decisions and open questions — but crabcakes could do this **automatically** as part of compaction, not just manually.

**Implementation:**
- New module: `models/spine.py` (or extend `models/conversation.py`)
- Spine extracted as part of `_last_exchange_summary()` (or its T1.2 successor)
- Injected into system prompt as `<conversation-spine>` block
- Spine itself becomes a checkpoint target (T2.1)

**Evidence:** Anthropic's "compaction + structured notes" cookbook. Letta's core memory blocks are spine-like. SPEC-4 (crabcakes' own dream consolidation spec) describes something similar at the cross-session level — T2.4 brings it to within-session.

---

### T2.5 — Context pressure signal + adaptive thresholds
**Source:** Production consensus across Cursor, Claude Code, OpenCode, LangChain
**Status:** Spec P1 has a static `compaction_threshold` per provider. Adaptive is a strict superset.
**Effort:** Low-Medium.

**What:** Track **context pressure** as a continuous signal:
- `pressure = (current_tokens + estimated_next_turn_cost) / soft_limit`
- When pressure > 0.85 → **preemptive compaction** (lighter touch: just one tool prune pass)
- When pressure > 0.95 → **emergency compaction** (full prune + trim + summary)
- When pressure < 0.50 after compaction → **back-off**: increase the `keep_first` budget for the next session

Different agents in the same runtime can have different policies:
- **Coder** (long sessions, lots of tool calls) — lower threshold (0.75)
- **Chat** (short, conversational) — higher threshold (0.90)
- **Auxilium** (advisory, no tool calls) — very high threshold (0.95)

**Why it's novel:** Spec P1 uses a single number per provider. Real systems adapt based on agent role + history. Cursor's UI has a "context meter" that turns yellow at 70%, red at 90% — that's a UX manifestation of this same idea. Crabcakes could expose pressure via the same `get_token_breakdown()` API that's already in `models/conversation.py`.

**Implementation:**
- Extend `get_token_breakdown()` to include `pressure` field
- Add `ContextPolicy` dataclass with per-agent-role thresholds
- Wire into `agent/runtime.py` tool loop for pre-turn pressure check

**Evidence:** Cursor's context meter is a direct UX form. Claude Code's 0.95 + OpenCode's 0.75 + Cline's 0.80 = "different thresholds for different situations" pattern is universal.

---

## Tier 3 — Cutting-edge research, high effort

### T3.1 — Agentic memory operations (A-Mem / AgeMem)
**Source:** [arXiv:2502.12110](https://arxiv.org/abs/2502.12110) A-Mem (NeurIPS 2025); [arXiv:2601.01885](https://arxiv.org/abs/2601.01885) AgeMem (2026)
**Status:** Beyond current scope but architecturally significant.
**Effort:** High. Requires new agent training or careful prompt-engineering.

**What:** Give the agent **memory operation tools**:
```python
@tool
def memory_store(content: str, tags: list[str], links_to: list[str] = None): ...

@tool
def memory_search(query: str, top_k: int = 5): ...

@tool
def memory_link(from_id: str, to_id: str, relation: str): ...  # Zettelkasten
```

The agent decides when to store, when to retrieve, when to link memories. Memory is **self-organized**.

**Why it's novel:** A-Mem reports that letting the agent organize its own memory outperforms pre-defined pipelines. AgeMem (RL-trained) outperforms Mem0 and A-Mem by 4.8–8.6 points on long-horizon benchmarks. This is the frontier.

**Implementation:**
- Pure-runtime approach: define tools, let the model call them. A-Mem style.
- Training-required approach: AgeMem RL. Out of scope for crabcakes unless we add RL training infrastructure.

**Trade-off:** Agent-controlled memory can be wasteful (agent stores too much) or lossy (agent forgets critical things). Requires careful prompts + audit logs.

---

### T3.2 — Temporal knowledge graph memory (Zep/Graphiti)
**Source:** [Zep architecture paper](https://storage.ghost.io/c/79/c4/79c4903e-2432-4c0e-b8c8-c8988fef71ec/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf)
**Status:** Major architectural change. Out of immediate scope but worth noting.
**Effort:** High. Requires graph DB integration (Neo4j, Memgraph, or sqlite-graph).

**What:** Replace the linear `messages: list[Message]` with a **temporal knowledge graph** where:
- Nodes are entities, events, decisions
- Edges are relationships with **temporal validity windows**
- Each fact can be queried "what was true at time T?"

**Why it's novel:** Zep achieves 94.8% on Deep Memory Retrieval vs MemGPT's 93.4%. Bi-temporal model (event time + transaction time) is **unique in the ecosystem**. Lets agents reason about preference changes over time.

**Implementation:** Significant. Requires new storage backend, new query language, new schema. Not a near-term addition but the obvious "next level" of memory once basic context management is solid.

---

### T3.3 — Token-eviction proxy via importance scoring
**Source:** LLMLingua-2 ([arXiv:2403.12968](https://arxiv.org/abs/2403.12968)); PRISM ([arXiv:2412.18914](https://arxiv.org/abs/2412.18914))
**Status:** Academic frontier; not yet in production frameworks.
**Effort:** Medium-High.

**What:** Run a small classifier over each token/message to decide "keep or discard", using a model distilled from GPT-4's compression behavior. Compress context by removing low-importance tokens while keeping message structure intact.

**Why it's novel:** Current crabcakes operates at message granularity (whole messages kept or removed). Token-level granularity would preserve more information per-token-budget.

**Trade-off:** Adds inference cost (small classifier), complexity, and risk of breaking tool-call JSON formatting.

---

## What's NOT recommended for crabcakes

After the deep dive, here's what the research surfaced but I'd recommend **against** for crabcakes:

| Technique | Why not |
|-----------|---------|
| **Infini-attention** (recurrent compression in attention layer) | Requires model architecture change + retraining. Provider concern. |
| **H2O / SnapKV / FastGen** (KV-cache eviction) | These are model-internal optimizations. Provider concern. Crabcakes can only affect the *prompt structure*. |
| **Multi-agent context coordination** | Unsolved across industry. Not actionable. |
| **Async summarization** (Aider pattern) | Requires threading model changes. Single-process agent is simpler. |
| **Semantic file partial reads** (Context-Engine-AI) | Needs tree-sitter/MCP integration. Separate epic. |
| **RL-trained memory agents** (AgeMem) | Requires training infrastructure. Defer until proven in simpler form. |
| **Full Zep-style graph DB** | Major architectural shift. Re-evaluate after T2.x stabilizes. |

---

## Proposed roadmap

| Phase | Scope | Effort | Builds on |
|-------|-------|--------|-----------|
| **P8** | Recursive hierarchical summarization (T1.1) + Structured summary schemas (T1.2) | Low | P1–P7 |
| **P9** | Tool-output offloading (T1.3) + Per-tool retention (T1.5) | Low-Medium | P4 |
| **P10** | Just-in-time file context retrieval (T1.4) | Medium | `agent/context.py` |
| **P11** | Checkpointing (T2.1) + Context pressure adaptive thresholds (T2.5) | Low-Medium | P1 |
| **P12** | Conversation spine (T2.4) + Position-aware reordering (T2.3) | Medium | P5, P8 |
| **P13** | Dream consolidation (T2.2 — extends SPEC-4) | High | Cross-session |
| **(future)** | Agentic memory tools (T3.1) | High | T1.4, T2.x |
| **(future)** | Temporal knowledge graph (T3.2) | Very High | New architecture |

---

## Key takeaways

1. **The spec just shipped (P1–P7) puts crabcakes at parity with the best open-source agents.** Anything beyond is genuinely novel.

2. **Three patterns dominate the 2026 frontier:** (a) structured/typed memory, (b) just-in-time retrieval over preloading, (c) tool-aware retention policies. All three are tractable for crabcakes.

3. **The single biggest leverage point is T1.3 (tool-output offloading).** It moves crabcakes from "lossy compaction" to "lossless compaction with selective retrieval" — a categorical improvement.

4. **The most architecturally interesting is T1.2 (structured summaries) + T2.4 (conversation spine).** Together they give crabcakes a **persistent self-model** of what the agent is doing — something no current open-source agent has cleanly.

5. **Don't chase academic KV-cache research** — those are provider-level concerns. Focus on **prompt structure** (position, ordering, offloading) which is what crabcakes actually controls.

6. **The dream consolidation (T2.2) is already in SPEC-4** but partial. Filling it in is a separate epic but builds on the same T1.x primitives.

---

## Sources

### Academic
- Wang et al., "Recursively Summarizing Enables Long-Term Dialogue Memory" — [arXiv:2308.15022](https://arxiv.org/abs/2308.15022)
- Xiao et al., "StreamingLLM" — [arXiv:2309.17453](https://arxiv.org/abs/2309.17453) (ICLR 2024)
- Packer et al., "MemGPT" — [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- Munkhdalai et al., "Infini-attention" — [arXiv:2404.07143](https://arxiv.org/abs/2404.07143)
- Xu et al., "A-Mem" — [arXiv:2502.12110](https://arxiv.org/abs/2502.12110) (NeurIPS 2025)
- Chhikara et al., "Mem0" — [arXiv:2504.19413](https://arxiv.org/abs/2504.19413) (ECAI 2025)
- Yu et al., "AgeMem" — [arXiv:2601.01885](https://arxiv.org/abs/2601.01885)
- "PRISM" — [arXiv:2412.18914](https://arxiv.org/abs/2412.18914) (EMNLP 2025)
- "LLMLingua-2" — [arXiv:2403.12968](https://arxiv.org/abs/2403.12968)
- "RULER" — [arXiv:2404.06654](https://arxiv.org/abs/2404.06654) (COLM 2024)
- "BABILong" — [arXiv:2406.10149](https://arxiv.org/abs/2406.10149) (NeurIPS 2024)

### Production
- Anthropic, "Effective context engineering for AI agents" — [anthropic.com](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Anthropic, "Effective harnesses for long-running agents" — [anthropic.com](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- LangChain, "Context engineering for agents" — [langchain.com](https://www.langchain.com/blog/context-engineering-for-agents)
- Cursor, "Self-summarization" — [cursor.com](https://cursor.com/blog/self-summarization)
- OpenAI, "ChatGPT memory and dreaming" — [openai.com](https://openai.com/index/chatgpt-memory-dreaming/)
- OpenAI, "Responses API context management" — [developers.openai.com](https://developers.openai.com/api/docs/guides/context-management)
- Letta architecture — [docs.letta.com](https://docs.letta.com/concepts/memory-management)
- Mem0 — [mem0.ai](https://mem0.ai/), [arxiv:2504.19413](https://arxiv.org/abs/2504.19413)
- Zep/Graphiti — [getzep.com](https://www.getzep.com/)
- LlamaIndex memory — [docs.llamaindex.ai](https://docs.llamaindex.ai/en/stable/module_guides/storing/chat_stores/)
- AWS Bedrock AgentCore Memory — [docs.aws.amazon.com](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)

### Crabcakes internal
- `docs/proposals/PROPOSAL-context-management-roadmap.md` (the proposal that became the spec)
- `docs/specs/SPEC-CONTEXT-MANAGEMENT-ROADMAP.md` (the just-shipped spec)
- `docs/research/CONTEXT-MANAGEMENT-SOURCE-OF-TRUTH.md`
- `docs/research/hidden-gems-agent-context-management.md`

---

*Synthesized June 25, 2026, from three parallel deep-research surveys (academic frontier, production systems, novel techniques) totaling ~8,000 words across 50+ sources.*