# Proposal: Context Management Phase 2 — Beyond the Open-Source Frontier

**Author:** Qaster (supervisor)
**Date:** 2026-06-25
**Status:** Awaiting captain review
**Severity:** MEDIUM — Phase 1 (P1–P7, shipped via SPEC-CONTEXT-MANAGEMENT-ROADMAP) brings crabcakes to parity with the best open-source agents. This phase goes beyond parity to adopt 2026 frontier patterns from academic papers and production platforms.

**Source research:**
- `docs/research/crabcakes-future-context-strategies.md` (synthesis of three deep research surveys)
- `docs/research/context-management-survey-2026.md` (academic frontier: arxiv, NeurIPS, ICLR, EMNLP)
- `docs/research/llm-context-management-research.md` (production systems: LangChain, LlamaIndex, Letta, Zep, Mem0, OpenAI, Anthropic, Cursor, Bedrock)

**Related proposals:**
- `docs/proposals/PROPOSAL-context-management-roadmap.md` (2026-06-25, ship-pending — P1 through P7)
- `docs/proposals/PROPOSAL-context-bloat-fix.md` (2026-06-16, SHIPPED — CB-1 through CB-5)

**Architecture alignment:** This proposal modifies components documented in ARCHITECTURE.md §3.21l (`models/conversation.py`), §3.21m (`agent/runtime.py`), §3.21p (`agent/context.py`), and §4.4b (System Prompt Budget). All changes respect the layering rules in §2: `models/` has no UI/network/LLM dependencies, `agent/` has no UI dependencies, `utils/` has no GTK imports.

---

## 1. Executive Summary

The Context Management Roadmap (P1–P7, ship-pending) closes the gap with the best open-source agents (Cline 0.80 threshold, OpenCode two-layer, OpenHands `keep_first`, Aider role-anchoring, OpenHands hard reset, summary-on-trim). After Phase 1, crabcakes has parity.

**What remains unsolved by Phase 1:**

Phase 1 is **delete-only** at the message level and **lossy** at the tool-output level. When a tool result is too large (P4), it's stubbed to 200 chars and the data is gone forever. When the conversation exceeds budget (P1), entire messages are deleted with a free-text summary replacing them. Neither approach supports **on-demand re-retrieval** — the agent can never get back what was pruned.

Additionally, Phase 1's summary is a **single free-text string**. There's no structured representation of "decisions made", "constraints in effect", "files touched", or "open questions". When the agent later needs to remember what was decided, it has to re-read the summary and hope the detail survived summarization.

This phase proposes **5 changes** (T1.1–T1.5) that bring crabcakes to 2026 frontier parity with production systems (Anthropic Claude Code, LangChain Deep Agents, Letta, OpenCode `PRUNE_PROTECTED_TOOLS`, ChatGPT "dreaming") and academic research (PRISM, Wang et al. hierarchical summarization). Priorities are ordered by **leverage per unit of effort**:

1. **T1.1 Recursive hierarchical summarization** — summary-of-summaries for long sessions
2. **T1.2 Structured summary schemas (PRISM)** — typed digests vs free text
3. **T1.3 Tool-output offloading (Anthropic "tool clearing")** — lossless vs lossy stub
4. **T1.4 Just-in-time file context retrieval** — inverse of current 50K-char preload
5. **T1.5 Per-tool retention policy (OpenCode `PRUNE_PROTECTED_TOOLS`)** — fine-grained vs uniform pruning

Together, these turn crabcakes' compaction from **emergency deletion** into **stratified, on-demand memory**.

---

## 2. Problem Statement

### 2.1 Phase 1's Lossy Compaction

After P4 ships, the runtime pipeline looks like:

```
tool result > 2000 chars → stub to 200 chars + flag
budget exceeded → delete oldest messages → inject free-text summary
```

This is **emergency management**, not memory. Two failure modes:

**Lossy tool outputs.** A 50KB `exec_command` output (e.g., test runner results) gets compressed to 200 chars. The agent loses the ability to re-check whether tests X and Y passed in turn N+5. The information is structurally gone from the conversation — there's no path to recover it short of re-running the tool.

**Free-text summaries.** A 50-turn conversation that gets summarized to 500 chars loses structure. "What did the user decide about auth?" requires the agent to either remember the summary string verbatim or guess. Structured representations (`decisions: ["use JWT", "rotate keys every 30 days"]`) survive summarization better than prose.

### 2.2 Preloaded File Context Waste

`agent/context.py:485 build_system_prompt()` currently always dumps a 50KB file context into every system prompt. This is paid for on **every turn**, regardless of whether the agent needs it.

A 2026 consensus pattern (Anthropic, LangChain, Letta): **store the file index in context, let the agent pull files via tool call when needed**. Saves tokens when the agent is doing tool work, spends tokens when the agent is doing file analysis. Net savings depend on the workload but production deployments report 25–40% reduction.

### 2.3 Uniform Tool Retention

Phase 1's `prune_tool_outputs()` treats every tool result equally: stub after N turns past last use. In practice:

- A `web_search` result might be referenced 3 turns later for verification
- A `memory_read` result might be referenced for the entire session
- An `exec_command` result is usually referenced only in the immediately following assistant turn

Uniform pruning loses information from the long-tailed tools and over-preserves the noise.

---

## 3. Recommendations

### 3.1 T1.1 — Recursive Hierarchical Summarization

**Source:** Wang et al. [arXiv:2308.15022](https://arxiv.org/abs/2308.15022); Anthropic "context engineering" cookbook; Letta/MemGPT production
**Supersedes:** P5's single-level summary
**Effort:** Low

**What:** Phase 1's summary is a single growing string. Replace it with a **stratified stack** of summaries: each new user turn generates a fresh leaf (L_n), periodic background rollups combine leaves into coarser parents (L_{n-1}, L_{n-2}).

```
Conversation:
  T1 → S1 (leaf)
  T2 → S2 (leaf)
  ...
  T_k → S_k (leaf)

Rollup trigger (every 3 leaves):
  S1, S2, S3 → R1 (parent)
  S4, S5, S6 → R2 (parent)
  ...
```

**Why it's novel:** Phase 1's "growing single summary" works for short conversations and **fails** for long ones — each new trim rewrites the entire summary, losing the old arc. Stratified memory preserves the arc at the top while keeping recent exchanges fine-grained at the leaves. Anthropic's "structured notes / STATE.json" pattern is exactly this; Letta's recall-memory compaction is a production instance.

**Implementation sketch:**

```python
# In models/conversation.py:
@dataclass
class SummaryLayer:
    level: int             # 0 = oldest, N = newest
    content: str
    covers_turns: tuple[int, int]  # inclusive
    created_at: datetime

class Conversation:
    self._summary_layers: list[SummaryLayer] = []  # sorted oldest→newest

    def add_leaf_summary(self, content: str, turn_range: tuple[int, int]) -> None:
        self._summary_layers.append(SummaryLayer(
            level=0, content=content, covers_turns=turn_range, created_at=datetime.now()
        ))

    def rollup(self, threshold: int = 3) -> None:
        """Combine threshold leaves into one parent. Pure data — no LLM call."""
        leaves = [l for l in self._summary_layers if l.level == 0]
        if len(leaves) < threshold:
            return
        # Caller (agent/runtime.py) is responsible for the LLM call.
        # This method just marks which leaves were combined.
        ...
```

- **Layering compliance:** LLM call stays in `agent/runtime.py` (orchestrator). `models/conversation.py` only manages the data structure.
- **Rollup policy:** New `SummaryRollupPolicy` dataclass in `agent/config.py` — `rollup_threshold: int = 3`, `max_layers: int = 5`.

**Evidence:** Wang et al. show hierarchical summarization consistently beats full-context and single-level summarization on long-horizon dialogue benchmarks. Mem0 production reports 91% latency reduction partly from stratified retrieval (Mem0g graph layer).

---

### 3.2 T1.2 — Structured Summary Schemas (PRISM)

**Source:** [arXiv:2412.18914](https://arxiv.org/abs/2412.18914) PRISM (EMNLP 2025 / ICLR 2026); LlamaIndex `FactExtractionMemoryBlock`
**Supersedes:** P5's `_last_exchange_summary()` returning free-text string
**Effort:** Low

**What:** Replace free-text summary with a **typed schema**:

```python
@dataclass
class ConversationDigest:
    arc: str                          # one-line overall narrative arc
    decisions: list[str]              # things that were decided
    constraints: list[str]            # constraints the agent operates under
    open_questions: list[str]         # unresolved threads
    referenced_paths: list[str]       # files / symbols touched
    blocked_attempts: list[str]       # things tried and rejected
    user_preferences: list[str]       # preferences expressed
    token_estimate: int
```

Serialized as `Message(role="assistant", content=json.dumps(...), is_summary=True)`. The agent later queries it like any tool result.

**Why it's novel:** Free-text summaries lose **searchability**. When the agent later asks "did we decide on JWT or session cookies?", it has to remember or re-read the whole summary. Structured digests are **queryable**: the agent (or a downstream tool) can extract just the `decisions` list and reason over it. PRISM's core insight is that **code-as-memory is more reliable than text-as-memory** — typed schemas survive summarization better than prose.

**Implementation:**

```python
# In models/conversation.py:
@dataclass
class ConversationDigest:
    arc: str = ""
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    blocked_attempts: list[str] = field(default_factory=list)
    user_preferences: list[str] = field(default_factory=list)
    token_estimate: int = 0

    def to_message(self) -> Message:
        return Message(
            role=MessageRole.ASSISTANT,
            content=json.dumps(asdict(self), indent=2),
            is_summary=True,
        )

    def merge(self, other: "ConversationDigest") -> "ConversationDigest":
        """Rollup helper for T1.1 — concatenates lists, prepends older arc."""
        return ConversationDigest(
            arc=f"{other.arc} | {self.arc}" if self.arc else other.arc,
            decisions=list(dict.fromkeys(other.decisions + self.decisions)),
            constraints=list(dict.fromkeys(other.constraints + self.constraints)),
            # ... etc
        )
```

- **Stdlib only:** `dataclasses` + `json` (no PyPI deps).
- **Layering compliance:** `ConversationDigest` is pure data. The LLM call that **generates** the digest lives in `agent/runtime.py`.

**Evidence:** PRISM achieves 4× shorter contexts while *outperforming* baselines — code-structured memory is denser than text summaries. LlamaIndex's `FactExtractionMemoryBlock` is the production proof.

---

### 3.3 T1.3 — Tool-Output Offloading (Anthropic "Tool Clearing")

**Source:** [Anthropic Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); LangChain Deep Agents "Write" primitive
**Supersedes:** P4's lossy 200-char stub
**Effort:** Low

**What:** When a tool result exceeds a threshold (e.g., 5,000 chars), **write it to disk** and replace the in-context content with a path + preview + a `tool_read_path` tool:

```python
@dataclass
class OffloadedToolResult:
    path: str              # relative path from project root (e.g., ".crabcakes/tool-outputs/conv-abc/msg-42.txt")
    preview: str           # first 200 chars
    byte_count: int
    line_count: int

# In agent/runtime.py tool loop:
if len(result.content) > 5000:
    offloaded = offload_tool_result(conv_id, msg_id, result.content)
    stub_message = (
        f"[Offloaded to {offloaded.path} — {offloaded.byte_count} bytes, "
        f"{offloaded.line_count} lines. Preview: {offloaded.preview!r}. "
        f"Call tool_read_path({offloaded.path!r}) to retrieve full content.]"
    )
```

When the agent needs the full content, it calls the built-in `tool_read_path` tool, which reads the file and returns it (with the same offloading rules applied recursively for tool output).

**Why it's novel:** Phase 1's stub is **lossy** — once stubbed, the data is gone. Offload is **lossless** — the full content lives on disk, retrievable on demand. Anthropic's Claude Code uses exactly this pattern for repo files; LangChain Deep Agents formalizes it as the "Write" primitive. The agent can re-fetch the data **iff** it needs it, rather than paying for it on every turn.

**Implementation:**

- **New dataclass:** `OffloadedToolResult` (above).
- **New file:** `agent/offload.py` with `offload_tool_result(conv_id, msg_id, content) -> OffloadedToolResult` and `read_offloaded_tool_result(path) -> str`.
- **Extend `prune_tool_outputs()`:** add `mode: Literal["stub", "offload"] = "stub"` parameter. P4 ships with `mode="stub"` (default, backward compatible). T1.3 promotes `mode="offload"` to default.
- **New tool entry:** `tool_read_path` in `default.md` tool list.
- **Disk layout:** `.crabcakes/tool-outputs/{conv_id}/{msg_id}.txt` (matches existing `.crabcakes/` convention).
- **Cleanup:** Offloaded files are pruned by the same `prune_tool_outputs()` logic — when the message they back is deleted, the file is also deleted.

**Trade-off:** Disk usage. A long session might accumulate ~50MB of offloaded outputs. Mitigations: (a) compress with gzip on write, (b) prune aggressively when a conversation is closed, (c) allow user-configurable disk budget via `agent/config.py`.

**Evidence:** Anthropic reports up to 54% improvement on agent benchmarks from context engineering alone, with tool-result clearing as the highest-ROI tactic. Cursor's context engineering plugin ranks tool-output offload as the #1 priority for compression.

---

### 3.4 T1.4 — Just-in-Time File Context Retrieval

**Source:** LangChain "Write/Select/Compress/Isolate" framework; Anthropic just-in-time retrieval; Letta `file_search`
**Status:** No equivalent in Phase 1 or spec.
**Effort:** Medium (touches `agent/context.py` and adds tools)

**What:** Replace the always-on 50K-char file context preload with an **index in context + tools for on-demand retrieval**:

```
[File index: 142 files, ~50K chars. Top entries:
  src/agent/context.py — 541 lines — context management
  src/agent/runtime.py — 2316 lines — LLM orchestration
  ...
Call file_search('symbol') or file_read('path') to retrieve content.]
```

Built-in tools:
- `file_search(query: str)` — BM25 or embedding-based search over file index, returns top-K paths + first lines
- `file_read(path: str, line_range?: tuple[int, int])` — reads full file or specific range
- `directory_tree(path: str, depth: int = 2)` — recursive listing

**Why it's novel:** Phase 1 always pays 50K chars for file context on every turn, even when the user is asking about tool execution or conversation history. JIT inverts this: pay the index cost (small) always, pay the full content cost (large) only when needed. 2026 production consensus (Anthropic, LangChain, Letta, Cursor) all converge on this pattern.

**Implementation:**

```python
# In agent/context.py:
@dataclass
class JITContextIndex:
    files: list[FileSummary]   # path, byte_count, line_count, first_line_preview

    def to_prompt(self) -> str:
        lines = [f"[File index: {len(self.files)} files, "
                 f"{sum(f.byte_count for f in self.files)} bytes. "
                 f"Use file_search('symbol') or file_read('path') to retrieve.]"]
        # ... list top entries by relevance
        return "\n".join(lines)

# In utils/prompt_loader.py:
def _truncate_file_context_smart(
    template_result: str,
    file_context_section: str,
    model_max_tokens: int,
    jit: bool = False,  # NEW
) -> str:
    if jit:
        # Build index from file_context_section instead of inlining it.
        index = JITContextIndex.from_text(file_context_section)
        return template_result.replace("{{FILE_CONTEXT}}", index.to_prompt())
    # ... existing logic
```

**Trade-off:**
- **Adds tool-call latency.** Each `file_read` adds a tool round-trip. For a single file read, this is slower than preloading. For an agent that reads 1 of 20 files in context, this is faster overall.
- **Default to JIT for long sessions**, preload for short ones. New config knob: `context_jit_threshold_turns: int = 10` (turn count after which JIT kicks in).

**Evidence:** LangChain benchmarks show ~30% token reduction with negligible quality loss when using Select for stable, large contexts. Anthropic's Claude Code used JIT to handle entire codebases without blowing context windows.

---

### 3.5 T1.5 — Per-Tool Retention Policy (OpenCode `PRUNE_PROTECTED_TOOLS`)

**Source:** OpenCode `prune()`; `docs/research/hidden-gems-agent-context-management.md`
**Supersedes:** P4's uniform `prune_tool_outputs(soft)`
**Effort:** Low

**What:** Different tools have different **post-use value**:

| Tool | Turn persistence | Rationale |
|------|------------------|-----------|
| `read_file` | 1 turn | Forgotten after next agent turn |
| `exec_command` | 1 turn | Forgotten after next agent turn |
| `file_search` | 3 turns | May be re-checked for verification |
| `web_search` | 5 turns | Often referenced across multiple reasoning steps |
| `memory_read` | session | Stays relevant for entire session |

```python
@dataclass
class ToolRetentionPolicy:
    default_turns_to_keep: int = 1
    per_tool: dict[str, int] = field(default_factory=lambda: {
        "web_search": 5,
        "memory_read": 999,
        "file_search": 3,
        "read_file": 1,
        "exec_command": 1,
    })

    def turns_to_keep(self, tool_name: str) -> int:
        return self.per_tool.get(tool_name, self.default_turns_to_keep)
```

`prune_tool_outputs()` consults this policy and **skips protected tools entirely** (or extends their retention to the configured turns).

**Why it's novel:** Phase 1 treats all tool outputs equally. Real conversations have wildly different tool value profiles. OpenCode's `PRUNE_PROTECTED_TOOLS` list was the highest-impact "hidden gem" finding from crabcakes' own research — protecting just 3 critical tools reduced agent errors by 40% in long sessions.

**Implementation:**

- Add `ToolRetentionPolicy` to `agent/config.py` (it's a config knob, not a runtime invariant).
- Add `last_used_turn_idx: int` to `Message` dataclass (or a sidecar dict on `Conversation`).
- Modify `prune_tool_outputs(target_tokens, protect_turns, policy)` to skip protected tools.

**Evidence:** OpenCode's research (crabcakes' own `hidden-gems-agent-context-management.md`) showed 40% reduction in agent errors on long sessions with per-tool retention.

---

## 4. Recommended Delivery Order

| Phase | Scope | Depends on | Estimated effort |
|-------|-------|------------|------------------|
| **P8** | T1.1 + T1.2 (recursive + structured summaries) | P5 | 2–3 days |
| **P9** | T1.3 (tool-output offload) | P4 | 1–2 days |
| **P10** | T1.4 (JIT file context) | `agent/context.py` | 3–4 days |
| **P11** | T1.5 (per-tool retention) | P4 | 1 day |

Total: ~7–10 days of focused implementation, follow standard loop (spec → phase instructions → builder → adversarial audit → commit).

---

## 5. What's NOT Included (and Why)

### 5.1 Tier 2 — Architecturally novel, deferred to Phase 3

- **T2.1 Conversation checkpointing** — user-controlled undo + agent time-travel debugging. Valuable but no current user pain driving it.
- **T2.2 Dream consolidation** — partially covered by SPEC-4 (cross-session). Implementation deferred.
- **T2.3 Position-aware reordering** — academic attention-mechanics optimization. Useful but **easy to get wrong** without empirical validation on crabcakes' specific workloads.
- **T2.4 Conversation spine** — persistent self-model surviving compaction. Powerful but requires substantial `agent/context.py` refactor.
- **T2.5 Adaptive thresholds per agent role** — different compaction thresholds for Coder vs Chat vs Auxilium. Easy to add once P1 ships, but better to validate P1 first.

### 5.2 Tier 3 — Cutting-edge, deferred indefinitely

- **T3.1 Agentic memory operations (A-Mem)** — let agent call `memory_store`/`memory_search`/`memory_link`. Powerful but adds tool surface area that needs UX design.
- **T3.2 Temporal knowledge graph (Zep/Graphiti)** — replace linear messages with bi-temporal graph. Architecturally invasive; better as a v3 rewrite than v2 incremental.
- **T3.3 Token-level importance classifier (LLMLingua-2)** — distilled GPT-4 token-discard model. Useful but requires shipping a model artifact.

### 5.3 KV-Cache Eviction (H2O, SnapKV, FastGen, Infini-attention)

These are **model-internal optimizations** — provider-side concerns. Crabcakes can only affect *prompt structure*, not attention mechanisms. Chasing this would be a category error. (Explicitly addressed in the source research: "What's NOT recommended for crabcakes".)

---

## 6. Success Metrics

After P8–P11 ship, expected outcomes (validated against 2026 production deployments):

- **Token reduction:** 25–40% reduction in average prompt tokens for long sessions (driven by T1.3 offload + T1.4 JIT).
- **Compaction frequency:** 50%+ reduction in compaction events (driven by T1.3 lossless offload replacing lossy stub).
- **Agent accuracy:** 30%+ reduction in "agent forgot what we decided" errors (driven by T1.2 structured digests).
- **Long-session stability:** Sessions exceeding 100 turns no longer exhibit the "amnesia at turn 80" failure mode (driven by T1.1 stratified summaries).

These are targets for empirical validation post-ship, not guarantees.

---

## 7. Architecture Compliance Checklist

For each item, verify before implementation:

- [ ] T1.1: LLM call for rollup lives in `agent/runtime.py`, not `models/conversation.py`.
- [ ] T1.2: `ConversationDigest` is stdlib-only (dataclasses + json). No PyPI deps.
- [ ] T1.3: Offload directory is `.crabcakes/tool-outputs/{conv_id}/`. Matches existing convention.
- [ ] T1.4: `file_search`/`file_read` tools added to `default.md` tool list and registered in `agent/tools/`.
- [ ] T1.5: `ToolRetentionPolicy` lives in `agent/config.py` (config knob), not `models/conversation.py` (data invariant).
- [ ] All items: CB-6 tool-call pairing invariant preserved.
- [ ] All items: no new PyPI dependencies.
- [ ] All items: layering rules from ARCHITECTURE.md §2 respected.

---

## 8. Open Questions for Captain Review

1. **T1.4 default behavior:** Should JIT be the default for new sessions, or opt-in? Recommendation: opt-in via `context_jit_threshold_turns` config, default 10 turns.
2. **T1.3 disk budget:** Default `.crabcakes/tool-outputs/` budget? Recommendation: 100MB per session, configurable.
3. **T1.1 rollup LLM model:** Use the same model as the main conversation, or a cheaper one? Recommendation: same model for consistency; if latency is an issue, allow a cheaper model in `agent/config.py`.
4. **T1.2 schema fields:** Are `decisions` / `constraints` / `open_questions` / `referenced_paths` / `blocked_attempts` / `user_preferences` the right fields, or should we trim? Recommendation: trim to 4 fields (`arc`, `decisions`, `constraints`, `referenced_paths`) for v1; add others based on user feedback.

---

## 9. Related Proposals

- `docs/proposals/PROPOSAL-context-management-roadmap.md` — Phase 1 (P1–P7), ship-pending.
- `docs/proposals/PROPOSAL-context-bloat-fix.md` — Phase 0 (CB-1 through CB-5), shipped.
- `docs/proposals/PROPOSAL_PRIORITY_ROADMAP_2026-06-12.md` — how this fits the broader 2026 roadmap.

---

**End of proposal.**