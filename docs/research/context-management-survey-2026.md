# Context Management Strategies for LLM Conversations: A Comprehensive Survey (2023–2026)

*Deep research survey covering academic papers, industry blogs, and conference proceedings on frontier techniques beyond naive rolling-window summarization.*

---

## Table of Contents

1. [Attention Sink / Streaming LLM Techniques](#1-attention-sink--streaming-llm-techniques)
2. [Memory Hierarchies](#2-memory-hierarchies)
3. [KV-Cache Compression & Token Eviction](#3-kv-cache-compression--token-eviction)
4. [Importance Scoring at Message/Token Level](#4-importance-scoring-at-messagetoken-level)
5. [Recursive / Streaming Summarization](#5-recursive--streaming-summarization)
6. [Tool-Call Aware Context Management](#6-tool-call-aware-context-management)
7. [Context Distillation](#7-context-distillation)
8. [Long-Context Benchmarks & What They Reveal](#8-long-context-benchmarks--what-they-reveal)
9. [Production Frameworks & Industry Approaches](#9-production-frameworks--industry-approaches)
10. [Cross-Cutting Themes & Synthesis](#10-cross-cutting-themes--synthesis)

---

## 1. Attention Sink / Streaming LLM Techniques

### StreamingLLM (Xiao et al., ICLR 2024)
- **Paper**: "Efficient Streaming Language Models with Attention Sinks" — [arXiv:2309.17453](https://arxiv.org/abs/2309.17453)
- **What it does**: Identifies that decoder-only LLMs give abnormally high attention scores to the first few tokens ("attention sinks"). These tokens anchor the attention distribution. StreamingLLM pins a small prefix (e.g., first 4 tokens) and uses a sliding window for everything else, enabling unbounded input streams without fine-tuning.
- **Novelty**: Moves beyond naive sliding-window by discovering that *which* tokens you pin matters more than how many. The sink tokens are structurally important, not semantically important.
- **Implementability**: ✅ Single-process, no retraining needed. Pin first N tokens + rolling window. Simple KV-cache layout change.
- **Open-source**: Reference implementation in paper; integrated into vLLM's design discussions. Community implementations widely available.

### Attention-Gate (2024)
- **Paper**: "In-context KV-Cache Eviction for LLMs via Attention-Gate" — [arXiv:2410.12876](https://arxiv.org/abs/2410.12876)
- **What it does**: Introduces a lightweight module that takes global context and produces per-token eviction flags, allowing dynamic, content-aware cache pruning — generalizing StreamingLLM's fixed policy.
- **Novelty**: Replaces fixed "sink + window" with learned, context-dependent eviction decisions.
- **Implementability**: ⚠️ Requires adding a small trainable module; not pure inference-time.

### PagedEviction (2025)
- **Paper**: [arXiv:2509.04377](https://arxiv.org/abs/2509.04377)
- **What it does**: Block-wise eviction compatible with paged KV layouts (e.g., vLLM's PagedAttention), rather than per-token eviction across pages.
- **Novelty**: Aligns eviction with memory page boundaries for practical deployment.
- **Implementability**: ✅ Inference-time, compatible with existing paged-attention systems.

### Infini-attention (Google, 2024)
- **Paper**: "Leave No Context Behind: Efficient Infinite Context Transformers with Infini-attention" — [arXiv:2404.07143](https://arxiv.org/abs/2404.07143)
- **What it does**: Combines masked local attention (current segment) with a fixed-size compressive memory (recurrent summary of all past segments). Memory is updated recurrently after each segment, enabling effectively infinite context with bounded VRAM.
- **Novelty**: Embeds recurrent memory *inside* the attention layer itself. Achieves 114× memory compression vs. Memorizing Transformers. A 1B model trained on 5K sequences correctly retrieves passkeys at 1M tokens.
- **Implementability**: ⚠️ Requires model architecture modification + continual pretraining. Not drop-in for existing models.
- **Open-source**: [github.com/a-r-r-o-w/infini-attention](https://github.com/a-r-r-o-w/infini-attention)

---

## 2. Memory Hierarchies

### MemGPT / Letta (Packer et al., 2023→2024)
- **Paper**: "MemGPT: Towards LLMs as Operating Systems" — [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- **What it does**: Draws inspiration from OS hierarchical memory (registers → cache → RAM → disk). Provides virtual context management with paging between context window ("main memory"), searchable recall database, and vector-indexed archive. The LLM itself manages memory via function calls.
- **Novelty**: First major system to treat context management as an OS-style resource scheduling problem, not just compression.
- **Implementability**: ✅ Agent-runtime level. No model retraining. Now productionized as [Letta](https://research.memgpt.ai/).
- **Note**: As of September 2024, MemGPT is part of Letta.

### A-Mem: Agentic Memory (Xu et al., NeurIPS 2025)
- **Paper**: "A-MEM: Agentic Memory for LLM Agents" — [arXiv:2502.12110](https://arxiv.org/abs/2502.12110)
- **What it does**: Combines Zettelkasten-style structured note organization with dynamic memory operations. Unlike MemGPT's predefined access patterns, A-Mem enables the LLM to dynamically organize memories — adding, linking, and restructuring notes autonomously.
- **Novelty**: Moves from fixed memory pipelines to *agentic* memory — the LLM decides how to organize its own memory space, creating links and structures dynamically.
- **Implementability**: ✅ Agent-runtime level. Works with any LLM.
- **Open-source**: [github.com/agiresearch/a-mem](https://github.com/agiresearch/a-mem)

### Mem0 (Chhikara et al., ECAI 2025)
- **Paper**: "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory" — [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)
- **What it does**: Production-grade memory layer that dynamically extracts, consolidates, and retrieves salient information from ongoing conversations. Features graph-based memory (Mem0g) for entity-relationship modeling. Single-pass hierarchical extraction at multiple abstraction levels. Multi-signal retrieval (semantic, temporal, recency).
- **Novelty**: First memory system explicitly benchmarked at production scale (1M–10M token conversations). Reports 91% lower p95 latency and >90% token savings vs. full-context. Temporal reasoning +29.6 points, multi-hop +23.1 points over original algorithm.
- **Implementability**: ✅ Drop-in memory service. Model-agnostic. Simple `.add()` / `.search()` API.
- **Open-source**: [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) | [mem0.ai](https://mem0.ai)

### AgeMem: Agentic Memory (Yu et al., 2026)
- **Paper**: "Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management" — [arXiv:2601.01885](https://arxiv.org/abs/2601.01885)
- **What it does**: Unifies LTM and STM management into a single RL-trained policy. Memory operations (ADD, UPDATE, DELETE, RETRIEVE, SUMMARY, FILTER) become tool-based actions the LLM learns to invoke optimally. Three-stage training: supervised warm-up → task-level RL → step-wise GRPO for fine-grained credit assignment.
- **Novelty**: Memory management is no longer hand-coded infrastructure — it's a *learned skill*. The agent learns when to store, compress, retrieve, and forget through reinforcement learning.
- **Implementability**: ⚠️ Requires RL training pipeline. Outperforms Mem0 and A-Mem by 4.8–8.6 points on long-horizon benchmarks.
- **Open-source**: Reference implementations emerging; [github.com/MaoChen1980/nanobot-agemem](https://github.com/MaoChen1980/nanobot-agemem)

### Hierarchical Memory for Long-Term Dialogue (2025)
- **Paper**: [arXiv:2507.22925](https://arxiv.org/abs/2507.22925)
- **What it does**: Three-tier architecture: Knowledge Layer (facts), Memory Trace Layer (sequential memory), Episode Layer (conversation episodes). Retrieval calculates similarity across layers rather than flat vector search.
- **Novelty**: Multi-resolution memory — different types of information stored at different granularities with layer-appropriate retrieval.

### Memory OS of AI Agent (2025)
- **Paper**: [arXiv:2506.06326](https://arxiv.org/abs/2506.06326)
- **What it does**: Proposes a full "operating system" abstraction for AI agent memory, managing scheduling, allocation, and persistence across heterogeneous memory stores.

---

## 3. KV-Cache Compression & Token Eviction

### H2O: Heavy-Hitter Oracle (Zhang et al., NeurIPS 2023)
- **Paper**: [NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/file/6ceefa7b15572587b78ecfcebb2827f8-Paper-Conference.pdf)
- **What it does**: Observes that attention weights follow a power-law — a small fraction of tokens ("heavy hitters") receive most attention mass. Keeps recent tokens + top-K heavy hitters by cumulative attention score. Formulates eviction as dynamic submodular maximization.
- **Novelty**: First rigorous attention-based eviction with theoretical justification. Keeps only ~20% of KV entries with minimal quality loss. Up to 29× throughput vs. HF Accelerate.
- **Implementability**: ✅ Training-free, inference-time only. Decoding-phase only (doesn't reduce prefill).
- **Limitation**: Evicted tokens are gone permanently (no retrieval).

### SnapKV (Li et al., 2024)
- **Paper**: [arXiv:2404.14469](https://arxiv.org/abs/2404.14469)
- **What it does**: Uses a small observation window (last N tokens of prompt) to estimate token importance via attention patterns. Applies 1D max-pooling to cluster importance scores, preserving contiguous semantic spans. Per-head selection.
- **Novelty**: Observation-window proxy for future attention + pooling-based clustering. Especially beneficial for retrieval tasks where important info concentrates in local spans.
- **Implementability**: ✅ Training-free, prefill-phase compression. Now a standard baseline for KV compression research.
- **Extension**: LAQ (Lookahead Q-Cache, EMNLP 2025) extends to decoding by generating pseudo queries as observation window.

### FastGen (Ge et al., ICLR 2024)
- **Paper**: "Model Tells You What to Discard: Adaptive KV Cache Compression for LLMs" — [arXiv:2310.01801](https://arxiv.org/abs/2310.01801)
- **What it does**: Profiles attention matrices after prefill to classify each head as local (sliding window), special-token-focused, or global (full cache). Constructs per-head adaptive eviction portfolio. ~50% KV memory reduction with negligible quality loss.
- **Novelty**: Per-head adaptive strategy based on actual attention behavior, not a one-size-fits-all policy.
- **Implementability**: ✅ Training-free. Requires custom CUDA kernels for irregular per-head KV layouts.
- **Open-source**: [github.com/machilusZ/FastGen](https://github.com/machilusZ/FastGen)

### Scissorhands (2023, widely adopted 2024)
- **What it does**: Based on "Persistence of Importance" hypothesis — tokens that receive high attention early tend to remain important throughout. Maintains accumulated attention scores and evicts low-importance tokens.
- **Novelty**: Formalizes temporal persistence of attention importance, enabling proactive eviction.

### KVMerger (2024)
- **Paper**: "Adaptive KV Cache Merging for LLMs on Long-Context Tasks"
- **What it does**: Instead of dropping evicted tokens, *merges* multiple KV states into a single representation using Gaussian-kernel-weighted merging. Retains top-K by attention + merges the rest.
- **Novelty**: Replaces binary keep/drop with many-to-one merging, preserving more information than pure eviction.

### L2 Norm-Guided Eviction (2024)
- **Paper**: "A Simple and Effective L2 Norm-Based Strategy for KV Cache Compression" — [EMNLP 2024](https://aclanthology.org/2024.emnlp-main.1027/)
- **What it does**: Discovers strong correlation between L2 norm of key embeddings and attention scores. Low L2 norm → high attention. Compresses KV cache using only key norms — no attention computation needed.
- **Novelty**: Attention-free eviction. Compatible with FlashAttention (which hides attention matrices). 50% reduction with no accuracy loss; 90% on passkey retrieval.
- **Implementability**: ✅ Extremely simple; just sort by key vector norms.

### HashEvict (2024–2025)
- **Paper**: [arXiv:2412.16187](https://arxiv.org/abs/2412.16187)
- **What it does**: Uses locality-sensitive hashing (LSH) to approximate cosine dissimilarity between current query and cached keys. Evicts most dissimilar token. Fully pre-attention.
- **Novelty**: Eliminates attention computation from eviction decisions entirely. 1.5–2× prefill speedup, up to 17× vs. FastGen.

### CAOTE & CriticalKV (2024–2025)
- **Papers**: [arXiv:2504.14051](https://arxiv.org/abs/2504.14051) (CAOTE), [arXiv:2502.03805](https://arxiv.org/abs/2502.03805) (CriticalKV)
- **What they do**: Optimize eviction with respect to actual output error. CAOTE integrates attention scores with value vector norms to estimate contribution to attention outputs. CriticalKV frames eviction from an output-perturbation perspective.
- **Novelty**: Goes beyond attention/importance proxies to directly model the downstream error from eviction decisions.

### Q-Hitter (MLSys 2024)
- **Paper**: [MLSys 2024](https://proceedings.mlsys.org/paper_files/paper/2024/file/bbb7506579431a85861a05fff048d3e1-Paper-Conference.pdf)
- **What it does**: Introduces quantization-aware token selection. Keeps tokens that are both heavy hitters AND friendly to low-bit quantization. Near-lossless 4-bit KV cache with up to 20× memory saving, 33× throughput.
- **Novelty**: First to co-optimize eviction and quantization friendliness.

### MiniCache (NeurIPS 2024)
- **What it does**: Compresses KV cache *across layers* by merging similar states in middle-to-deep layers. 1.53× cross-layer compression alone, up to 5.02× combined with 4-bit quantization.
- **Novelty**: Orthogonal dimension — depth-wise compression rather than sequence-wise. Combinable with all sequence-eviction methods.

---

## 4. Importance Scoring at Message/Token Level

### PRISM (EMNLP 2025 / ICLR 2026)
- **Paper**: "PRISM: Efficient Long-Range Reasoning with Short-Context LLMs" — [arXiv:2412.18914](https://arxiv.org/abs/2412.18914) | [ACL Anthology](https://aclanthology.org/2025.emnlp-main.517/)
- **What it does**: Uses structured schemas to distill long documents into code-composition memory. The LLM proposes which chunks to add to memory based on query relevance. Achieves 4× shorter contexts while outperforming baselines.
- **Novelty**: Code-as-memory — instead of text summaries, information is stored as executable/structured code fragments that the LLM composes and queries.
- **Implementability**: ✅ Agent-runtime level. No model training.

### Token Entropy Filtering (SirLLM, 2024)
- **What it does**: Uses token self-information (negative log-probability) to score importance. Retains high-entropy (surprising/informative) tokens plus sink tokens under memory budget.
- **Novelty**: Information-theoretic importance scoring — tokens that surprise the model are likely most informative.

### CONVERSE Encoder (NAACL 2024)
- **Paper**: [ACL Anthology](https://aclanthology.org/2024.naacl-long.6.pdf)
- **What it does**: Distills a lightweight conversation encoder that maps raw dialogues into a vector space aligned with LLM-produced summaries. Enables efficient conversational search without runtime summarization.
- **Novelty**: Distills the summarizer's behavior into a smaller encoder for retrieval, decoupling summarization cost from query-time latency.

---

## 5. Recursive / Streaming Summarization

### Recursively Summarizing Enables Long-Term Dialogue Memory (Wang et al., 2024)
- **Paper**: [arXiv:2308.15022](https://arxiv.org/abs/2308.15022) | [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0925231225008653)
- **What it does**: Progressively generates summaries of small dialogue contexts, then recursively summarizes those summaries. Creates hierarchical memory at multiple granularities. Tested with Llama, ChatGLM, and GPT-3.5-Turbo.
- **Novelty**: Formalizes recursive summarization as a structured approach (not ad-hoc), with automatic and human evaluation showing consistent improvement over full-context baselines.
- **Implementability**: ✅ Pure prompt-engineering + runtime. No model training.

### Acon: Optimizing Context Compression for Long-horizon Agents (2025)
- **Paper**: [arXiv:2510.00615](https://arxiv.org/abs/2510.00615)
- **What it does**: Compresses long agent trajectories by reducing resolution of entire turns (user message + agent response + tool calls + tool results) into compact summaries. Optimizes *when* and *what* to compress based on task structure.
- **Novelty**: Agent-trajectory-aware compression — understands that different parts of an agent's history have different compression tolerance.

### Recurrent Context Compression (OpenReview 2024)
- **Paper**: [OpenReview](https://openreview.net/forum?id=GYk0thSY1M)
- **What it does**: Maintains BLEU-4 ~0.95 on text reconstruction, ~100% accuracy on passkey retrieval at 1M tokens via learned recurrent compression.
- **Novelty**: Model-level compression that's trained, not heuristic.

### CCF: Context Compression Framework (2025)
- **Paper**: [arXiv:2509.09199](https://arxiv.org/abs/2509.09199)
- **What it does**: Summarizes input into compact representations at multiple levels. Parameter-efficient.

### DAST: Dynamic Context-Aware Compression (ACL Findings 2025)
- **Paper**: [ACL Anthology](https://aclanthology.org/2025.findings-acl.1055.pdf)
- **What it does**: Dynamic allocation of compression budget based on content-aware analysis of the input.

---

## 6. Tool-Call Aware Context Management

This is notably an area with **limited academic publication** but significant **production engineering** work. The consensus across sources:

### Core Invariant: Tool-Call/Result Atomicity
Every production system converges on the same rule: a `tool_use` and its matching `tool_result` form an **atomic unit**. You keep both or drop both — never one without the other. This is both an API correctness constraint (many providers reject orphaned tool calls) and a cognitive one (LLMs seeing half a pair hallucinate state).

### LangChain Deep Agents Context Engineering
- **Source**: [LangChain Blog — Context Management for Deep Agents](https://www.langchain.com/blog/context-management-for-deepagents) | [Docs](https://docs.langchain.com/oss/python/deepagents/context-engineering)
- **Strategy**: 
  - Offload large tool responses to filesystem when they exceed threshold (e.g., 20K tokens)
  - Replace raw result in context with file path/pointer + short preview
  - At ~85% context utilization, truncate older tool calls, keeping only pointers
  - Three-stage compression: (1) prune stale outputs, (2) offload large results, (3) semantic summarization

### Anthropic Context Engineering
- **Source**: [Anthropic Engineering Blog](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Strategy**:
  - **Tool-result clearing**: Drop re-fetchable tool outputs after they've served their purpose; keep only summary + identifiers
  - **Just-in-time retrieval**: Store file paths in context, not file contents; agent reads on demand (Claude Code pattern)
  - **Compaction**: Periodically summarize conversation history into structured summaries (decisions, constraints, open issues)
  - **Structured notes / memory tool**: Agent writes structured notes to external storage for cross-window continuity

### JetBrains Context Management (2025)
- **Source**: [JetBrains Research Blog](https://blog.jetbrains.com/research/2025/12/efficient-context-management/)
- **Strategy**: Compresses entire agent trajectories (turns + tool calls + results) into compact forms while preserving resolution of critical decision points.

### Pair-Aware Sliding Window (Multiple Implementations)
- **Sources**: [agent-message-window](https://dev.to/mukundakatta/agent-message-window-a-sliding-context-window-that-never-breaks-a-tool-pair-1kjh) | [agentfit-rs](https://dev.to/mukundakatta/agentfit-rs-token-aware-message-truncation-for-rust-llm-agents-45d0)
- **Algorithm**: Walk message list from oldest. When encountering `tool_use`, look forward for matching `tool_result`; drop both together. Token-aware variant groups messages into segments with tool pairs as indivisible units.

### Google Multi-Agent Framework
- **Source**: [Google Developers Blog](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)
- **Strategy**: Durable session log with compaction events. Each agent sees minimum necessary context via filtering and scoping.

### Piggybacked Compression
- Tag each tool result with IDs (`[tc1]`, `[tc2]`). On each new tool call, the LLM is instructed to summarize older results that are no longer needed — zero extra LLM calls for summarization.

---

## 7. Context Distillation

### Context Distillation as Training (2024)
- **Paper**: [arXiv:2409.01930](https://arxiv.org/abs/2409.01930)
- **What it does**: Trains a student model to internalize task-specific examples that would otherwise be in the prompt. Student models match ICL accuracy in-domain and generalize better out-of-domain.
- **Novelty**: Moves context from prompt-time to model-weights — the model "memorizes" what would otherwise need to be in context every time.
- **Implementability**: ⚠️ Requires training pipeline.

### LLMLingua-2 (2024)
- **Paper**: [arXiv:2403.12968](https://arxiv.org/abs/2403.12968)
- **What it does**: Distills GPT-4's compression knowledge into a token-classification model. Formulates prompt compression as preserve/discard binary classification per token. Creates extractive compression dataset from MeetingBank.
- **Novelty**: Data-distillation approach — learns *what to keep* from a powerful teacher, rather than using entropy/perplexity heuristics.
- **Implementability**: ✅ Small classifier model runs alongside main LLM. Training-free at inference (classifier is pre-trained).
- **Open-source**: [llmlingua.com](https://llmlingua.com/llmlingua2.html)

### DiSCo Meets LLMs (2024)
- **Paper**: [arXiv:2410.14609](http://arxiv.org/pdf/2410.14609.pdf)
- **What it does**: Distills similarity scores between conversations and documents, unifying retrieval and context modeling for conversational search.
- **Novelty**: Trains models to implicitly model "what documents or previous interactions are relevant to this conversation" — future-query awareness through representation learning.

### Query-Conditioned Summarization
- **Concept** (from multiple 2024 sources): When summarizing a conversation, include the current query or task type so the summarizer focuses on likely future-relevant info. Structure summaries into fields: facts likely to matter, user preferences, outstanding questions, references.
- **Implementability**: ✅ Pure prompt engineering.

### Layered Compression Strategy
From practice-oriented sources:
1. **Distilled representations** of older context (user profile, long-term goals, recurring constraints)
2. **Summarized versions** of recent context (last session's decisions, unresolved questions)
3. **Consolidated or raw** immediate context (last N messages verbatim)

This makes the system naturally future-query-aware: the distilled layer encodes *what is likely to matter again*, not just what happened.

---

## 8. Long-Context Benchmarks & What They Reveal

### RULER (NVIDIA, COLM 2024)
- **Paper**: [arXiv:2404.06654](https://arxiv.org/abs/2404.06654) | [GitHub](https://github.com/NVIDIA/RULER)
- **What it tests**: 13 tasks across 4 categories (retrieval, multi-hop tracing, aggregation, QA) at configurable lengths up to 32K+.
- **Key finding**: Nearly all models ace vanilla NIAH (needle-in-a-haystack), but **sharp degradation** on multi-hop and aggregation tasks. Only ~half of models claiming ≥32K context maintain satisfactory performance at 32K. **Passing NIAH does not guarantee long-context reasoning.**
- **Extension**: RULER v2 adds systematic difficulty levels; OneRuler (2025) extends to 26 languages.

### BABILong (NeurIPS 2024)
- **Paper**: [arXiv:2406.10149](https://arxiv.org/abs/2406.10149) | [GitHub](https://github.com/booydar/babilong)
- **What it tests**: Adapts Facebook bAbI tasks to extreme lengths (4K → 50M tokens). 20 reasoning tasks: fact chaining, induction, deduction, counting, state tracking.
- **Key finding**: Standard LLMs effectively use only **~10–20% of available context**. Multi-hop reasoning collapses much earlier than single-fact retrieval. Memory-augmented architectures (RMT, Mamba, ARMT) dramatically outperform standard transformers at extreme lengths.
- **SOTA**: ARMT achieves ~79.9% accuracy at 50M tokens on QA1.

### LongBench v1/v2/Pro (2023–2025)
- **Papers**: [LongBench v1](https://aclanthology.org/2024.acl-long.172.pdf) | [LongBench v2](https://arxiv.org/abs/2412.15204) | [LongBench Pro](https://arxiv.org/abs/2601.02872)
- **What they test**: Bilingual (EN/ZH), multi-task, realistic long-context understanding. v2 focuses on deep reasoning; Pro evaluates 46 LLMs on 1,500 natural samples (8K–256K).
- **Key findings**:
  - **Long-context optimization > parameter scaling**: Better attention mechanisms yield larger gains than bigger models.
  - **Effective context < claimed context**: Models break down well before their advertised maximum.
  - **Inference-time reasoning helps — but only if natively trained**: Chain-of-thought benefits models trained for it; degrades those that aren't.
  - **RAG diminishing returns**: Beyond ~32K tokens, adding more retrieved text without structured reasoning produces little benefit.
  - **Safety failures**: LongSafetyBench shows models overlook harmful content in lengthy texts.

### What Failures Collectively Teach Us

1. **Retrieval ≠ Reasoning**: Models can find needles but can't reason over multiple scattered facts reliably.
2. **Context windows are over-marketed**: Usable context is typically 10–50% of claimed maximum.
3. **Reasoning complexity kills performance faster than length**: Multi-hop tasks degrade much earlier than single-hop.
4. **Structured context management matters more than raw size**: Beyond ~32K tokens, intelligent selection/compression beats raw inclusion.
5. **Architecture matters**: Memory-augmented and recurrent architectures substantially outperform pure attention at extreme lengths.
6. **Safety attenuates**: Long contexts can cause models to miss or discount dangerous content.

---

## 9. Production Frameworks & Industry Approaches

### LangChain: Write, Select, Compress, Isolate (2025)
- **Source**: [LangChain Blog](https://www.langchain.com/blog/context-engineering-for-agents) | [GitHub](https://github.com/langchain-ai/context_engineering)
- Four operational primitives for agent context:
  - **Write**: Persist memory outside the window (notes, DB rows, files)
  - **Select**: Retrieve only what the current turn needs (just-in-time, tool-based)
  - **Compress**: Summarize and prune as history grows (state-triggered compaction at ~70% token budget)
  - **Isolate**: Give each sub-agent only its relevant slice (specialized prompts, multi-agent harnesses)

### Anthropic: Context Engineering Playbook (2025)
- **Source**: [Anthropic Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | [Harnesses Post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | [Tools Cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- **Golden rule**: Use the minimum number of high-quality tokens that achieve desired behavior.
- **Key patterns**: Compaction, tool-result clearing, structured notes/memory, just-in-time retrieval, multi-agent harnesses (initializer + coding agent phases).
- **Result**: Up to ~54% improvement on agent benchmarks from context engineering alone.

### Galileo: Context Engineering for Agents
- **Source**: [Galileo Blog](https://galileo.ai/blog/context-engineering-for-agents)
- Focuses on context poisoning, distraction, confusion, and clash — failure modes where low-quality context degrades agent performance.

### Memory Benchmarks (2025–2026)
- **BEAM**: Tests production-scale memory at 1M and 10M token conversations. Mem0 scores 64.1 on BEAM (1M).
- **LoCoMo**: Long-conversation memory evaluation.
- **LongMemEval**: Long-term memory evaluation across sessions.
- **MemoryAgentBench / MemBench / MemoryArena** (2025–2026): Tightly couple memory with action evaluation.

---

## 10. Cross-Cutting Themes & Synthesis

### The Convergence of KV-Cache Eviction and Context Management
Academic KV-cache compression (H2O, SnapKV, FastGen) operates at the *model inference* level — inside the attention mechanism. Agent context management (MemGPT, Mem0, LangChain) operates at the *application* level — structuring what goes into prompts. The frontier is where these meet: systems that understand both the model's internal attention economics and the application's semantic structure.

### From Fixed Policies to Learned Memory Behaviors
Clear trajectory:
1. **Fixed policies** (rolling window, recency-based) → 2020–2022
2. **Attention-based heuristics** (H2O, StreamingLLM, Scissorhands) → 2023
3. **Adaptive/content-aware** (SnapKV, FastGen, norm-guided) → 2024
4. **Agentic/Learned** (A-Mem, AgeMem with RL) → 2025–2026

### The Tool-Call Problem: Solved in Practice, Unpublished in Academia
Nearly every production system implements tool-call/result pair preservation, but there's a conspicuous lack of peer-reviewed research formalizing this. The gap between production engineering (LangChain, Anthropic, JetBrains) and academic KV-cache work is notable. This represents an opportunity for formalization.

### What Actually Works in Production (2026 Consensus)
From the convergence of Mem0, Anthropic, LangChain, and JetBrains:
1. **Layered memory** (raw recent → summarized mid-term → distilled long-term)
2. **Just-in-time retrieval** over pre-loading
3. **Tool-result clearing** with pointer preservation
4. **State-triggered compaction** (e.g., at 70% token budget)
5. **Multi-agent isolation** for complex workflows
6. **Structured notes** for cross-session continuity

### What's Not Yet Solved
1. **Future-query-aware compression**: No system reliably predicts what will be needed later and optimizes compression accordingly.
2. **Cross-modal context**: How to manage tool results that are images, tables, code, etc.
3. **Safety in compressed contexts**: Does compaction preserve safety-relevant information?
4. **Formal guarantees on tool-call invariants**: No peer-reviewed framework for proving context management preserves agent correctness.
5. **Memory quality metrics**: No standard way to measure whether stored memories are accurate, non-redundant, and useful.
6. **The "effective context" gap**: Models claiming 1M tokens typically degrade well before that; benchmarks consistently show 10–50% effective utilization.

---

## Summary Table: Technique → Implementability

| Technique | Category | Single-Process Runtime? | Requires Retraining? | Key Reference |
|-----------|----------|------------------------|---------------------|---------------|
| StreamingLLM | Attention sink | ✅ | ❌ | arXiv:2309.17453 |
| H2O | KV eviction | ✅ | ❌ | NeurIPS 2023 |
| SnapKV | KV eviction (prefill) | ✅ | ❌ | arXiv:2404.14469 |
| FastGen | Adaptive KV | ✅ | ❌ | ICLR 2024 |
| L2-Norm Eviction | KV eviction | ✅ | ❌ | EMNLP 2024 |
| HashEvict | LSH-based KV | ✅ | ❌ | arXiv:2412.16187 |
| KVMerger | KV merging | ✅ | ❌ | 2024 |
| Infini-attention | Recurrent memory | ❌ | ✅ | arXiv:2404.07143 |
| MemGPT/Letta | Memory hierarchy | ✅ | ❌ | arXiv:2310.08560 |
| A-Mem | Agentic memory | ✅ | ❌ | arXiv:2502.12110 |
| Mem0 | Production memory | ✅ | ❌ | arXiv:2504.19413 |
| AgeMem | Learned memory | ⚠️ | ✅ (RL) | arXiv:2601.01885 |
| LLMLingua-2 | Prompt compression | ✅ | ❌ | arXiv:2403.12968 |
| Recursive Summary | Summarization | ✅ | ❌ | arXiv:2308.15022 |
| Pair-Aware Trimming | Tool-call mgmt | ✅ | ❌ | Production blogs |
| Anthropic CE | Full framework | ✅ | ❌ | Anthropic blog |
| LangChain WSCI | Full framework | ✅ | ❌ | LangChain blog |
| PRISM | Schema distillation | ✅ | ❌ | arXiv:2412.18914 |

---

*Survey compiled June 2026. ~30 distinct sources consulted across arxiv, conference proceedings (NeurIPS, ICLR, EMNLP, ACL, COLM, MLSys, ECAI), industry blogs (Anthropic, LangChain, JetBrains, Google, NVIDIA, Mem0), and open-source repositories.*
