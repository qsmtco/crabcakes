# Production LLM Context Management Strategies: Deep Research Report

*Compiled June 25, 2026 — covers frameworks, platforms, and chat products in production.*

---

## 1. LangChain (Legacy Memory + LangGraph State)

**Docs:** https://docs.langchain.com/oss/python/concepts/memory  
**Engineering blog:** https://www.agilesoftlabs.com/blog/2026/05/longterm-ai-agent-memory-with-langchain

### Current State (2025–2026)

LangChain's classic memory classes (`ConversationBufferMemory`, `ConversationSummaryMemory`, `ConversationSummaryBufferMemory`, `ConversationBufferWindowMemory`, `VectorStoreRetrieverMemory`, `EntityMemory`) are now considered **legacy "black-box" memory objects**. The framework has shifted toward **LangGraph** — explicit state management with graph nodes, checkpoints, and external stores — rather than opaque drop-in memory classes.

### Memory Strategies (Classic, Still Available)

| Class | Strategy | Use Case |
|-------|----------|----------|
| `ConversationBufferMemory` | Store all messages verbatim | Short bounded sessions (<20–30 turns) |
| `ConversationBufferWindowMemory` | Keep last K messages (sliding window) | Cost-controlled short sessions |
| `ConversationSummaryMemory` | Running LLM-generated summary | Long-running dialogues, cross-session |
| `ConversationSummaryBufferMemory` | Summary of old + verbatim recent | Hybrid: long sessions with recent precision |
| `VectorStoreRetrieverMemory` | Embed messages, retrieve by similarity | Long-term semantic recall |
| `EntityMemory` | Extract and store entity-keyed facts | User profiles, relationship tracking |

### Modern Production Pattern: Layered Hybrid

The 2025–2026 best practice is a **layered architecture**:

- **Buffer (short-term):** `ConversationBufferWindowMemory` (K=10–20), in-memory or Redis
- **Summary (mid-term):** `ConversationSummaryMemory`, persisted in Postgres/Supabase, summarized every 10–20 turns
- **Vector (long-term):** `VectorStoreRetrieverMemory` with pgvector/Pinecone/Weaviate for facts, events, documents
- **Entity (profile):** Relational DB for user preferences, stable attributes

### Key Parameters & Thresholds

- Buffer window: last 10–20 exchanges typical
- Summarization cadence: every 10–20 turns (not every message — cost control)
- Time-weighted retrieval for recent memory boosting
- Hybrid retrieval: semantic + full-text + recency recommended for production

### Distinctive Insights

LangChain's own roadmap now emphasizes **"agent memory engineering"** over selecting a single Memory class. LangSmith Agent Builder treats memory as **files** (procedural memory in config, semantic in skill files, episodic via conversation history files) — a significant philosophical shift from the old class-based approach.

---

## 2. LlamaIndex Chat Memory

**Docs:** https://docs.llamaindex.ai/en/stable/module_guides/storing/chat_stores/  
**Memory blog:** https://www.llamaindex.ai/blog/improved-long-and-short-term-memory-for-llamaindex-agents  
**API reference:** https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/

### Architecture: Three-Layer Memory Stack

**Layer 1 — Short-Term (`ChatMemoryBuffer`):**
- Keeps last X messages under a token limit (default varies; configurable)
- FIFO eviction when limit exceeded
- `ChatSummaryMemoryBuffer` variant summarizes older messages to fit within token budget

**Layer 2 — Long-Term (`Memory` + Memory Blocks):**
- `Memory` coordinates short-term buffer + one or more **Memory Blocks**:
  - **`StaticMemoryBlock`** — fixed facts (profile, config). Priority 0 (never truncated)
  - **`FactExtractionMemoryBlock`** — LLM extracts structured facts from flushed chats
  - **`VectorMemoryBlock`** — embeds flushed chats into vector store, retrieves relevant ones at query time

**Layer 3 — Chat Stores (Persistence):**
- `SimpleChatStore` (in-memory, JSON persistence) — dev only
- `RedisChatStore` (remote, persistent) — production
- Custom DB-backed implementations

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `token_limit` | 30,000 | Total tokens across short + long-term memory |
| `chat_history_token_ratio` | 0.7 | Fraction reserved for short-term chat history |
| `token_flush_size` | 3,000 | Tokens to flush from short-term to long-term blocks |

### Flush & Truncation Logic

When chat history exceeds the `chat_history_token_ratio` threshold, old messages are **flushed into memory blocks** (long-term). At retrieval time:
- Blocks queried in **descending priority order**
- Results injected until token limits met
- When long-term blocks exceed their limits, truncation iterates in **ascending priority** order
- **Priority 0 blocks are never truncated** (use for essential static data)

### Distinctive Insights

LlamaIndex's block-based architecture is notably flexible — you compose memory blocks like Unix pipes. The `FactExtractionMemoryBlock` provides structured fact extraction (e.g., "User is vegetarian", "Uses VS Code and Python") rather than raw semantic search, enabling more precise personalization.

---

## 3. Letta (formerly MemGPT)

**Docs:** https://docs.letta.com/concepts/memory-management  
**Blog:** https://www.letta.com/blog/agent-memory  
**Architecture paper:** https://docs.letta.com/concepts/memgpt

### Core Concept: "LLM OS" with Virtual Context

Letta/MemGPT treats the LLM like an operating system managing **virtual context** — the agent actively pages information in and out of its context window using tool calls, enabling effectively unlimited memory within fixed context.

### Three-Tier Memory Hierarchy

**Tier 1 — Core Memory (RAM):**
- Named **memory blocks** rendered directly into the prompt as XML
- Typical blocks: `persona` (agent role/behavior), `human` (user profile), additional task blocks
- **Always visible** to the agent on every turn
- **Self-editing**: agent uses tool calls (`edit_in_context_memory`) to update blocks
- Persisted to database immediately on change
- Block-size limits removed in v0.16.7; blocks can grow up to model context window

**Tier 2 — Recall Memory (Conversation Log):**
- Persistent log of all prior messages and interactions
- Agent calls `recall_search` tools to find specific past exchanges
- Overflow handling: **sliding window** of recent messages + automatic **summarization/compaction** of older segments
- Triggered when `total_tokens > context_window`

**Tier 3 — Archival Memory (Disk/Vector Store):**
- Backed by vector database (Chroma, pgvector)
- Long-running facts, documents, prior task knowledge
- Agent calls `archival_memory_search` for embedding similarity retrieval
- Retrieved snippets temporarily paged into context

### Letta V1 Evolution (2025)

- **Deprecated:** heartbeats (periodic ticks), `send_message` meta-tool
- **Retained:** MemGPT-style memory hierarchy, now in a cleaner agent runtime
- **New (Agent SDK / "MemFS"):** Git-tracked filesystem memory with "agent dreaming" — agents maintain persistent filesystem state that is version-controlled, enabling rollbacks and diff-based memory inspection
- **Model-agnostic:** memory and state managed separately from LLM provider

### Distinctive Insights

Letta's key innovation is **agent-controlled memory management** — the LLM itself decides what to keep in core memory, when to search archival, and when to edit its own memory blocks. This contrasts with framework-controlled approaches (LangChain, LlamaIndex) where the application code manages memory. The new MemFS system adds git-style versioning to agent memory, a feature unique in the ecosystem.

---

## 4. Zep / Zep Cloud

**Site:** https://www.getzep.com/  
**Architecture paper:** https://storage.ghost.io/c/79/c4/79c4903e-2432-4c0e-b8c8-c8988fef71ec/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf

### Core Architecture: Temporal Knowledge Graph (Graphiti)

Zep's defining feature is **Graphiti**, a temporal knowledge graph engine that represents memory as a time-aware dynamic graph G = (N, E, φ):

- **Nodes (N):** entities, events, concepts, communities
- **Edges (E):** relationships and facts between nodes
- **Incidence function φ:** links edges to endpoints

### Bi-Temporal Model

Every fact/edge carries **temporal validity metadata**:
- **Event time:** when the fact occurred in the real world
- **Transaction time:** when Zep ingested the information

When new conflicting information arrives, Graphiti **invalidates the old fact's validity window** (sets end time) and **creates a new fact** — retaining full historical record. This is **non-lossy**: agents can query "what was true when?" and trace how preferences evolved.

### Hierarchical Subgraphs

- **Episodic subgraphs:** individual conversations/sessions with time ordering
- **Semantic subgraphs:** aggregated facts, entities, relationships across episodes
- **Community subgraphs:** patterns and groups discovered across many episodes (customer segmentation, shared preferences)

### Hybrid Retrieval Stack

- **Semantic vector search** (embeddings)
- **Keyword/BM25 search** (exact text matching)
- **Direct graph traversal** (relationship navigation, temporal constraints)
- Many queries answered **without LLM inference at retrieval time** — pure graph/IR operations

### Performance

On the Deep Memory Retrieval (DMR) benchmark: Zep achieves **94.8% accuracy vs. 93.4% for MemGPT**.

### Distinctive Insights

Zep's temporal knowledge graph is unique in the ecosystem. Most competitors use vector stores or simple key-value; Zep models **how facts change over time** with validity windows. This enables temporal reasoning ("What did the user prefer in March?") that's impossible with flat vector approaches. The bi-temporal model (event time vs. transaction time) comes from database research and is more sophisticated than any other memory layer in this survey.

---

## 5. Mem0

**Site:** https://mem0.ai/  
**Paper:** https://arxiv.org/abs/2504.19413  
**Docs:** https://docs.mem0.ai

### Architecture: Streaming Memory Pipeline + Hybrid Datastore

Mem0 sits between application and LLM as an **intelligent context manager**, intercepting conversation streams and managing memory model-agnostically.

### Three-Stage Pipeline

**1. Extraction Phase:**
- Input: recent messages (last N turns) + relevant past summaries
- LLM calls extract: summaries, facts, preferences, constraints, entities/relations
- Output: candidate memories (structured objects)

**2. Update / Consolidation Phase:**
- Second LLM call decides action per candidate:
  - **ADD** — insert new memory
  - **UPDATE** — modify existing when new info overwrites/refines old fact
  - **DELETE** — remove outdated/contradicted memory
  - **NO-OP** — ignore unimportant items
- Graph variant (Mem0g) includes **conflict detection** before committing

**3. Retrieval Phase:**
- **Semantic vector similarity** search
- **Graph queries/traversals** (Mem0g) for relational reasoning
- **Key-value lookups** for structured frequently-used facts (O(1) latency)
- Results ranked by **importance, recency, and relevance**

### Hybrid Datastore

| Store | Purpose | Retrieval |
|-------|---------|-----------|
| Vector store | Semantic similarity embeddings | "Find anything relevant to this query" |
| Graph store (Mem0g) | Entity-relationship triplets | Complex relational queries |
| Key-value store | Structured frequently-accessed facts | O(1) lookups (timezone, subscription tier) |

### Memory Scopes

- **User memory:** persists across all sessions for a specific user
- **Session memory:** short-term within a conversation
- **Agent memory:** specific to an agent instance (multi-agent isolation)

### 2026 Evolution

- **Single-pass ADD-heavy extraction:** agent-generated facts treated as first-class, always stored when relevant
- **Multi-signal retrieval:** semantic + keyword + entity matching in parallel, fused scores
- Designed for **token efficiency**: better recall with fewer memories injected

### Distinctive Insights

Mem0's explicit ADD/UPDATE/DELETE/NO-OP semantics via LLM tool calls is distinctive — most systems either append blindly or use opaque heuristics. The three-signal fusion retrieval (semantic + lexical + entity) addresses the known weakness of pure vector search (poor on exact matches and entity-specific queries). The research paper (arXiv:2504.19413) provides the most rigorous academic treatment of any memory layer in this survey.

---

## 6. OpenAI Assistants API → Responses API (Context Management Evolution)

**Assistants deep dive:** https://developers.openai.com/api/docs/assistants/deep-dive  
**Context management guide:** https://developers.openai.com/api/docs/guides/context-management  
**Conversation state:** https://developers.openai.com/api/docs/guides/conversation-state

### Assistants API (Being Deprecated August 26, 2026)

**Threads & Messages:**
- Limit: **100,000 Messages per Thread**
- When messages exceed the model's context window, the Thread **smartly truncates messages, before fully dropping the ones it considers least important**
- `max_prompt_tokens` and `max_completion_tokens` control per-Run token budgets
- Truncation strategy: `auto` (OpenAI's default smart truncation)

### Responses API (Successor)

**Original truncation controls:**
- `truncation: "disabled"` (default) — HTTP 400 if input exceeds context window
- `truncation: "auto"` — server silently drops items to fit (middle or beginning of conversation)

**2025–2026: Explicit Context Management & Compaction:**

- **`context_management` block with `compact_threshold`:**
  - When context size crosses threshold, OpenAI runs a **compaction pass** (summarization/restructuring)
  - Emits a **compaction output item** in the stream
  - Prunes context and continues inference with compacted state

- **Standalone `/responses/compact` endpoint:**
  - Send full context window to this endpoint
  - Returns a new compacted context window including compaction item
  - Stateless — designed specifically for context management
  - Use compacted output as input for subsequent `/responses` calls

### Realtime API Context Handling

- 32k token context window for `gpt-realtime`
- **Retention ratio parameter** (e.g., 0.8) — truncates 20% of context window rather than minimal truncation
- Context summarization cookbook pattern for long sessions

### Distinctive Insights

OpenAI's evolution from blind truncation → explicit compaction is significant. The `/responses/compact` endpoint as a **stateless context management primitive** is unique — you can use it independently of OpenAI's conversation state. The recommendation to treat `truncation: "auto"` as a **fallback safety mechanism** rather than primary strategy reflects hard-won production experience with "ultra aggressive truncation behavior" reported by developers.

---

## 7. Anthropic Claude — Projects, Memory & Context Engineering

**Engineering blog:** https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents  
**Memory announcement:** https://www.anthropic.com/news/memory  
**Context management:** https://www.anthropic.com/news/context-management

### Context Engineering Philosophy

Anthropic defines **context engineering** as: *"the art and science of curating what will go into the limited context window from a constantly evolving universe of possible information."* Key principle: **context is a finite resource with diminishing marginal returns.**

Research on **context rot** shows that as token count increases, model recall precision decreases — not a hard cliff but a performance gradient. The n² pairwise attention complexity of transformers means every token depletes an "attention budget."

### Claude Memory Stack (2025)

| Layer | What It Stores | Who Manages |
|-------|---------------|-------------|
| Live context window | Current turns + retrieved snippets | Anthropic runtime |
| Projects | Large uploaded files (docs, code, PDFs) | User (UI/API) |
| Built-in Memory | Key facts, preferences, project summaries | Claude + user UI |
| Memory Tool (API) | Arbitrary files/notes for agents | Developer + agents |

### Project-Scoped Memory

- Each **Claude Project** has its **own memory store and memory summary**
- Hard boundary: information from one project does **not bleed** into another
- Memory summaries updated on regular cadence (~daily)
- Users can view, edit, delete memories in settings

### Memory Tool (Developer Platform)

- Claude can **create, read, update, delete files** in a dedicated memory directory
- Persists across conversations and runs
- Enables agent-managed knowledge bases and workflow state

### Context Engineering Patterns (from Anthropic Cookbook)

- **Compaction:** Summarize long interactions into concise state files (`NOTES.md`, `STATE.json`)
- **Tool clearing:** Drop low-value history, keep only goals, decisions, and pointers
- **Persistent notes:** Project briefs the agent can reload
- **Structured formats:** Headings, bullet lists, schemas for machine-friendly summaries
- **Place critical information at beginning or end** of context — models attend more reliably to edges

### Distinctive Insights

Anthropic's framing of "context engineering" as the natural evolution of "prompt engineering" is influential across the industry. Their emphasis on **minimal high-signal tokens** and the Goldilocks principle (not too brittle/specific, not too vague) for system prompts is widely cited. The research-backed concept of **context rot** (from Chroma Research) provides empirical grounding for why aggressive context management matters.

---

## 8. Google Gemini API — Context Caching

**Docs:** https://ai.google.dev/gemini-api/docs/caching  
**Cloud docs:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview  
**Blog:** https://developers.googleblog.com/gemini-2-5-models-now-support-implicit-caching/

### Two Caching Modes

**Implicit Caching (Automatic):**
- Gemini 2.5+ models automatically detect when a request shares a common prefix with a previous request
- No explicit cache management needed
- **Discount applied automatically** when cache is hit
- To maximize hits: keep content at the **beginning of the request** the same, put variable content (user questions) at the **end**

**Explicit Caching (Manual):**
- Create a cache object with large content (text, audio, video files)
- Reference cached tokens in subsequent requests
- **Guaranteed discount** — predictable savings
- Minimum cache size: **2,048 tokens**
- Maximum: full model context window (up to 2M tokens for Gemini 2.5 Pro)
- Configurable **TTL** (time-to-live)
- Can be used via `cached_content` property in OpenAI-compatible libraries

### Long Context Handling

Gemini 2.5 Pro supports up to **2M tokens** — the largest context window among frontier models. Context caching is the primary strategy for cost-efficient long-context use:

- Cache large documents/codebases/videos once
- Send only the small variable prompt per request
- Pay discounted rate for cached tokens

### Distinctive Insights

Google's approach is fundamentally different from the memory-layer approaches — instead of managing what goes in/out of context, they **make large context affordable via caching discounts**. The implicit caching is notably developer-friendly (zero code changes). The 2M token window + caching makes Gemini uniquely suited for use cases requiring entire codebases or long video/audio analysis in a single context.

---

## 9. ChatGPT Memory Features

**OpenAI announcement:** https://openai.com/index/memory-and-new-controls-for-chatgpt/  
**"Dreaming" feature:** https://openai.com/index/chatgpt-memory-dreaming/  
**FAQ:** https://help.openai.com/articles/8590148-memory-faq

### Two-Layer Memory Architecture

**Layer 1 — Saved Memories (Explicit):**
- Triggered by "remember this," "remember that I..." phrases
- Stores structured facts: role, industry, preferences, ongoing projects
- Persists until user deletes; managed via Settings UI
- Later added **automatic prioritization** — less relevant memories deprioritized

**Layer 2 — Chat History / "Dreaming" (Implicit):**
- Introduced April 2025
- Background process **automatically curates memories** from chat history across all conversations
- Analyzes many conversations, synthesizes "memory state" with fresh insights
- Does NOT store everything — keeps most relevant information
- "Learning to forget": system actively moves less important details to background

### Retrieval Pipeline

1. **Trigger & classification:** Each message classified for store/forget signals
2. **Memory retrieval:** Searches saved memories + past conversation summaries (embeddings)
3. **Multi-tier storage:** Hot (recent/frequent), Warm (older relevant), Cold (archived)
4. **Conflict resolution:** Prioritizes most recent, most frequently referenced
5. **Context assembly:** Relevant memories formatted as structured snippets
6. **Memory with Search:** User preferences injected into web search queries

### Project Memory (August 2025)

- Scope memory to specific **projects**
- Summarized prior chats within that project only
- Prevents cross-contamination between client/work/personal

### Key Controls

- Global enable/disable toggle
- **Temporary Chat mode:** no memory use, no memory updates, excluded from training
- Per-memory deletion and "clear all"
- Conversational control: "remember" / "don't remember this"

### Distinctive Insights

The "dreaming" feature is ChatGPT's most novel contribution — an offline background process that synthesizes memories across conversations, analogous to how human memory consolidation works during sleep. The multi-tier hot/warm/cold storage with **automatic prioritization and de-prioritization** based on recency, frequency, and ongoing use is a production pattern rarely seen in open-source frameworks. The integration of memory into **search query rewriting** ("Memory with Search") is also distinctive.

---

## 10. AI Coding Assistants (Cursor, Continue.dev, Cody, Aider)

**Cursor blog:** https://cursor.com/blog/self-summarization  
**Context engineering plugin:** https://cursor.directory/plugins/context-engineering  
**Developer toolkit:** https://developertoolkit.ai/en/shared-workflows/context-management/

### Cursor

**Automatic Compaction:**
- Agent harness performs **self-summarization** when hitting context window cap
- Uses **sliding context window** — drops older turns, keeps recent
- Compaction runs **fully behind the scenes** — no explicit "summary message" in UI
- Context meter visible in chat UI; quality degrades past ~70–80% usage

**`/summarize` command:**
- Manual compaction trigger
- Strips unnecessary tool calls (exploration steps)
- Condenses long chats while preserving decisions/conclusions

**Key thresholds:**
- 128k–200k token context windows typical (Claude 3 MAX 200k, GPT-4o MAX 128k)
- Large-context mode can **double price** — disable when not needed
- Known bug: assumes **1M token context** for custom models without confirmation

**`.cursor/rules`:**
- Persistent conventions, standards, domain knowledge always available
- Re-injected on every turn (survives context truncation)

**Best practice: phased approach:**
- Research → Plan → Execute, each in separate chat
- Output saved to markdown files in repo
- Next phase loads via `@`-mentions

### Continue.dev

- **Explicit context selection** via `@` mentions (files, folders, symbols)
- Developer controls exactly what enters context — no automatic summarization
- Configurable **reserved token space**
- Philosophy: **targeted retrieval** as primary defense against context overflow
- Open-source; developers tune context pipeline themselves

### Sourcegraph Cody

- Research on **context-aware code retrieval** (arXiv:2408.05344)
- Key finding: system must balance **recall vs. precision** — select only a few highly relevant items
- Feeds **small, curated context chunks** rather than broad dumps
- Uses code search + embeddings + ranking for context selection

### Aider

- Terminal-based; relies on developer-managed context
- **Repo map** (tree-sitter-based) provides compressed codebase overview
- Automatically selects relevant files for context based on conversation
- No automatic compaction — developer manages session length

### Cross-Cutting Patterns

All coding assistants converge on:
- **Project memory files** (`.cursor/rules`, `AGENTS.md`, `CLAUDE.md`) for persistent context
- **Short focused sessions** preferred over mega-threads
- **File references** over folder dumps
- **Summaries over raw history** for long sessions
- Context as **working set, not database**

### Distinctive Insights

Cursor's behind-the-scenes self-summarization is the most aggressive automatic approach. The "context engineering plugin" formalizes best practices with operations: **Write** (save context externally when >70% utilization) and **Compress** (summarize while preserving information). The priority order for compression is revealing: **1) tool outputs (80%+ of tokens), 2) older turns, 3) retrieved documents** — and **never compress the system prompt**.

---

## 11. Haystack (deepset)

**Docs:** https://haystack.deepset.ai  
**Memory blog:** https://haystack.deepset.ai/blog/memory-conversational-agents  
**RAG guide:** O'Reilly "RAG in Production with Haystack"

### Pipeline-Based Memory

Haystack treats memory and retrieval as **separate pipeline components** that you wire together:

**Conversation Summary Memory:**
- Periodically summarizes recent exchanges
- Configurable `summary_frequency` (every N turns or per-turn)
- Summaries stored as compact context blocks

**Retrieval-Backed Memory:**
- Memory served through extractive QA pipeline or summarization pipeline
- Agent queries memory as needed rather than carrying everything in prompt

**Explicit Pipeline Control:**
- Haystack's strength is **pipeline transparency**: branching, looping, filtering, reranking, routing
- Memory, retrieval, tools, and generation remain visible and debuggable
- Production setups use hybrid search, query expansion, metadata-driven retrieval, self-reflective RAG, and reranking

### Production Architecture

- **Short-term state:** Active conversation in agent run (single run scope)
- **Long-term memory:** Separate memory system, retrieves relevant snippets on demand
- **Compression:** Summarize older dialogue, prune low-value turns
- **Selective recall:** Ranked memory retrieval or extractive QA over memory instead of raw history dump
- No built-in cross-session persistence — developers implement their own

### Distinctive Insights

Haystack is the most **explicit/pipeline-oriented** framework in this survey. Where LangChain abstracts memory into classes and LlamaIndex into blocks, Haystack treats every step as a pipeline component you can inspect, debug, and replace. This makes it the most transparent but also the most DIY — there's no "just add memory" button. The O'Reilly guide emphasizes that context engineering for RAG requires careful tuning of retrieval relevance before generation, not just bigger context windows.

---

## 12. AWS Bedrock Agents / Azure AI Agents / Vertex AI Agents

**Bedrock AgentCore Memory:** https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html  
**Blog:** https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/

### AWS Bedrock AgentCore Memory (Most Mature)

**Five Design Principles:**
1. **Abstracted storage** — handles infra for short/long-term memory
2. **Security** — encrypted at rest and in transit (AWS KMS or customer-managed keys)
3. **Continuity** — events stored chronologically for narrative flow
4. **Data organization** — hierarchical namespaces for structured memory + access control
5. **Scalability** — efficient large-volume handling with low latency

**Two Memory Types:**

*Short-Term Memory:*
- Raw interaction data as immutable events, organized by actor and session
- Events: USER/ASSISTANT/TOOL/SYSTEM messages
- Stored synchronously
- **Event expiry:** configurable, 1–365 days

*Long-Term Memory:*
- Persistent insights and preferences across sessions
- Automatic extraction of meaningful information from conversations
- **Memory ID** per user for isolation
- Structured summaries that agents recall in future interactions

**Episodic Memory (newer):**
- Agents learn from past experiences across tasks
- Stores episodes (task + approach + outcome) for future reference

### Azure AI Agents

- Relies more on **external state stores** and application-managed memory
- Conversation history persisted via Azure services
- No first-class managed memory product comparable to AgentCore
- Memory patterns left to developer implementation

### Vertex AI Agents

- Similarly app-managed context and session storage
- Leverages Gemini context caching (see Section 8) for cost-efficient long context
- No dedicated memory management service at parity with Bedrock

### Distinctive Insights

AWS Bedrock AgentCore Memory is the **most explicit managed memory service** among the three cloud providers. The configurable retention (1–365 days), per-user isolation via memoryId, and episodic memory for cross-task learning make it the most production-ready enterprise option. Azure and Vertex lag significantly in first-class memory primitives — developers building on these platforms typically need to build their own memory infrastructure or integrate third-party solutions like Mem0 or Zep.

---

## 13. DSPy

**Site:** https://dspy.ai  
**Optimizers:** https://dspy.ai/learn/optimization/optimizers/  
**GEPA optimization:** https://dspy.ai/getting-started/gepa-optimization/

### Core Idea: Tasks, Not Prompts

DSPy treats prompts as **code to be optimized**, not strings to be handcrafted. Context management happens at the **signature + module** level.

### Signatures (The Context Contract)

```python
class GenerateAnswer(dspy.Signature):
    """Answer the question using the given context."""
    context: str = dspy.Input(desc="Relevant passages or documents")
    question: str = dspy.Input(desc="User question")
    answer: str = dspy.Output(desc="Concise, correct answer")
```

- **Inline signatures:** `"question -> answer"` — quick experiments
- **Class-based signatures:** typed fields with descriptions — production
- Signatures define **what context flows between modules** — explicit, testable

### Modules (Prompting Strategy)

- **Predict:** basic input → output
- **ChainOfThought:** step-by-step reasoning with context
- **RAG modules:** `context + question → answer` integrating retrieved docs

### Programmatic Optimization (GEPA / Teleprompters)

- DSPy **compiles** programs against a metric:
  1. Generate variations of instructions and few-shot demos
  2. Run examples through candidates, score via metric
  3. Select best configuration
- Optimizers can improve **how the model uses context** (e.g., hallucination reduction instructions)
- Re-run optimizers when models change, data grows, or requirements shift

### Context Management via Chained Signatures

- Retrieval module: `query → retrieved_docs`
- Synthesis module: `retrieved_docs, question → answer`
- DSPy passes outputs as inputs between modules — **context flow is explicit and auditable**

### Distinctive Insights

DSPy is unique in this survey — it doesn't provide a "memory layer" but instead **programmatically optimizes how context is presented**. The idea that you should *let the framework find the optimal prompt configuration* rather than hand-engineering it is a paradigm shift. The chained signature pattern makes context flow between pipeline stages fully transparent, testable, and optimizable. For production RAG systems, DSPy's ability to optimize instructions about *how* the model uses retrieved context (not just what context is retrieved) addresses a gap no other system in this survey tackles.

---

## 14. AI21, Cohere, Mistral

**AI21 agent memory:** https://www.ai21.com/glossary/ai-agent/agent-memory/  
**Cohere cookbook:** https://github.com/cohere-ai/cohere-developer-experience  
**Mistral Agents API:** https://docs.mistral.ai/

### AI21

- **Layered context guidance:** short-term memory for session coherence, long-term for personalization
- Emphasizes **purge/archive policies** when memory becomes stale or compliance-relevant
- Alignment of retention to task needs — not all conversations need permanent memory
- Developer manages memory infrastructure; AI21 provides the LLM and agent reasoning

### Cohere

- **Augmented memory objects:** compact, interpretable units derived from reasoning and generation
- Fits a **compressed short-term memory** pattern rather than raw transcript storage
- Cookbook describes memory as structured reasoning artifacts, not conversation logs
- Focus on **enterprise deployments** with on-premise options

### Mistral

- **Agents API** manages conversation history as message arrays
- **Sliding window** approach: retain most recent and relevant messages to control token usage
- Supports **custom memory management**: selective forgetting, mid-conversation system-message injection
- Developer-side control: Mistral provides primitives, you build the memory strategy
- Reference chat template handles context assembly with system messages at top

### Cross-Cutting Pattern

All three take a **primitives-not-services** approach:
- Provide the LLM + basic agent loop
- Leave memory architecture to the developer
- Recommend the standard layered pattern: short-term buffer + compressed summaries + external long-term storage
- Emphasize **selective forgetting** and **isolation** by task/topic/agent role

### Distinctive Insights

None of these three offer a first-class managed memory product (unlike Mem0, Zep, or Bedrock). This reflects their positioning as **model providers** rather than **agent platform providers**. Developers building on AI21/Cohere/Mistral typically integrate third-party memory layers or build their own.

---

## Cross-Cutting Themes & Conclusions

### Universal Patterns

1. **Layered/hybrid memory is standard** — every mature system uses buffer + summary + external storage. No production system relies on a single strategy.

2. **Summarization cadence matters** — every 10–20 turns, not every message (cost control). All frameworks converge on this.

3. **Context is a finite resource with diminishing returns** — Anthropic's "context rot" research validates what practitioners observed empirically.

4. **System prompts should never be compressed** — this rule from Cursor's context engineering plugin is echoed by Anthropic, Letta, and others.

5. **Agent-controlled memory is emerging** — Letta's self-editing memory blocks and Mem0's ADD/UPDATE/DELETE semantics represent a shift from framework-controlled to agent-controlled memory.

6. **Temporal awareness is the frontier** — Zep's bi-temporal knowledge graph and Mem0's conflict detection address problems that simpler vector-only systems cannot solve.

7. **Caching vs. managing** — Google's approach (make large context affordable via caching) is philosophically opposite to the compression/summarization approach. Both are valid for different use cases.

8. **Coding assistants converge on file-based memory** — `.cursor/rules`, `AGENTS.md`, `CLAUDE.md` — persistent context files that survive session resets, because the chat window is unreliable as long-term storage.

### Key Thresholds Across Systems

| System | Trigger | Action |
|--------|---------|--------|
| LangChain | Every 10–20 turns | Summarize + prune |
| LlamaIndex | `chat_history_token_ratio` > 0.7 | Flush to long-term blocks |
| Letta/MemGPT | `total_tokens > context_window` | Summarize old segments |
| Cursor | ~70–80% context utilization | Self-summarize or `/summarize` |
| OpenAI | `compact_threshold` crossed | Compaction pass |
| Anthropic | Approaching token cap | Compaction + tool clearing |
| LlamaIndex | `token_flush_size` (default 3000) | Flush to memory blocks |

### The Spectrum: Framework-Controlled ↔ Agent-Controlled

```
Framework-controlled                    Agent-controlled
    │                                        │
    ├─ LangChain (app code manages)          ├─ Letta/MemGPT (agent self-edits)
    ├─ LlamaIndex (framework flushes)        ├─ Mem0 (agent ADD/UPDATE/DELETE)
    ├─ Haystack (pipeline components)        ├─ Anthropic Memory Tool (agent writes files)
    ├─ Cursor (harness auto-compacts)        └─ ChatGPT "dreaming" (background synthesis)
    └─ OpenAI (server-side compaction)
```

The industry is moving right — toward giving agents more autonomy over their own memory management, with safety guardrails (user controls, audit trails, rollback via git-style versioning).

---

*Report compiled from official documentation, engineering blogs, research papers, conference talks, and community resources. All URLs cited inline. ~3,800 words.*