# PROPOSAL: Knowledge-Graph-Enhanced Self-Improvement System

**Date:** 2026-05-26
**Authors:** QTR (with Captain JAQx)
**Status:** ⚠️ PARTIALLY DONE — MCP memory server is wired (agents can create/query entities via MCP tool merge). The structured schema and layer wiring (typed/weighted/temporal nodes for bugs, rules, audits, code changes) was never built. No `agent/knowledge_graph.py` or `utils/memory_graph.py` exists.
**Repository:** github.com/qsmtco/crabcakes

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — 
> **status:** `PARTIAL` — sortable tag for `ls | grep STATUS` The MCP memory server is wired (verified in `agent/runtime.py:1079-1082` — `mcp_servers` parameter and `get_tools_for_api` are used). Coder agents can create entities and relations via the MCP tool merge. However, the **structured schema and layer wiring** described in this proposal (typed/weighted/temporal nodes for bugs, rules, audits, code changes) is **not** built. There is no `agent/knowledge_graph.py` or `utils/memory_graph.py`. The knowledge graph is available as a tool but is not the active storage layer for the self-improvement system.

---

## Executive Summary

The existing Self-Improvement proposal (CODER_SELF_IMPROVEMENT_PROPOSAL.md) builds a 5-layer system on **flat files**: markdown bug journals, markdown project rules, audit reports in files. It works — but it's passive. It stores what happened without connecting it, weighting it, or drawing inferences from the topology.

This proposal replaces flat-file storage with a **knowledge graph** (backed by the MCP memory server already verified working in CrabCakes). Every bug, rule, test run, audit finding, and code change becomes a **typed, weighted, temporal node** with edges that create a queryable nervous system for the agent.

The result: the self-improvement system stops being a diary and starts being a **living graph** that can answer questions no flat file can — "what will break if I touch this?", "is this rule still valid?", "has this pattern appeared before, and how did we fix it?"

---

## What the MCP Memory Server Can Already Do

The `@modelcontextprotocol/server-memory` is verified working end-to-end:
- **9 tools:** create_entities, create_relations, add_observations, delete_entities, delete_observations, delete_relations, read_graph, search_nodes, open_nodes
- **Persistence:** JSONL file survives app restarts
- **Transport:** stdio subprocess
- **Tool merge:** MCP tools appear in agent tool list via `get_tools_for_api()`
- **End-to-end verified:** Coder created QontinuumBridge entity and powers relation through the UI

The infrastructure is ready. What's missing is the **schema** and the **layer wiring**.

---

## The Graph Schema

### Node Types

| Node Type | Fields | Example |
|-----------|--------|---------|
| `bug` | name, entityType, observations | `bug_042:mock-truthiness:watcher.py` |
| `pattern` | name, entityType, observations | `mock-truthiness` |
| `rule` | name, entityType, observations | `check-mock-type-not-truthiness` |
| `test_run` | name, entityType, observations | `test_watcher.py:2026-05-26T14:32` |
| `audit` | name, entityType, observations | `Qaster:PR47:2026-05-26` |
| `code_change` | name, entityType, observations | `watcher.py:commit_9a3c4f2` |
| `agent_imprint` | name, entityType, observations | `Coder_v1.2` |
| `file_entity` | name, entityType, observations | `watcher.py` |
| `function_entity` | name, entityType, observations | `_emit_moved:DashedHandler` |

### Edge Types

| From | Relation | To | Meaning |
|------|----------|-----|---------|
| bug | `is_type` | pattern | This bug exemplifies this pattern |
| bug | `affected` | file_entity | This bug touched this file |
| bug | `was_caught_by` | test_run | This test caught this bug |
| bug | `was_fixed_by` | code_change | This commit fixed this bug |
| bug | `same_pattern_as` | bug | These bugs share the same root cause |
| pattern | `observed_in` | [bug] | These bugs exemplify this pattern |
| pattern | `suggests` | rule | This pattern generates this rule |
| rule | `evidence` | [bug] | These bugs support this rule |
| rule | `enforced_by` | function_entity | This function enforces this rule |
| test_run | `triggered_by` | code_change | This test ran because of this change |
| test_run | `exposed` | bug | This test exposed this bug |
| audit | `found` | bug | This audit found this bug |
| code_change | `changed` | file_entity | This change modified this file |
| code_change | `changed` | function_entity | This change modified this function |

---

## Layer-by-Layer Enhancement

### Layer 1: Bug Journal → Living Graph

**Current:** Flat markdown file `.crabcakes/coder-bugs.md`. Each entry is a text block with fields like `Pattern: mock-truthiness`.

**Enhanced:** Every bug is an entity node. Every pattern is an entity node. Every relationship between them is a typed edge.

**Migration path:** One-time scan of existing `coder-bugs.md` entries → create entity + edges for each.

**Example entry:**
```json
{
  "name": "bug_042",
  "entityType": "bug",
  "observations": [
    "Task: Fix moved event detection in DebouncedHandler",
    "Mistake: Used dest_path is not None — MagicMock objects are always truthy",
    "Fix: Changed to isinstance(dest_path, str) and dest_path",
    "Lesson: Never check truthiness on mock objects",
    "Pattern: mock-truthiness",
    "Confidence: 0.94",
    "Root_cause: type-check on MagicMock",
    "Was_fixed_by: commit_7a3c4f2"
  ]
}
```

**Edges created:**
- bug_042 `is_type` mock-truthiness
- bug_042 `affected` watcher.py
- bug_042 `was_caught_by` test_watcher.py::test_moved_events
- bug_042 `same_pattern_as` bug_017

**What becomes possible:**
- Traverse backward from any file → all bugs that touched it, all patterns, all root causes
- Pattern nodes auto-cluster: "mock-truthiness has 12 bug nodes" — no manual tagging needed
- Confidence score per bug derived from evidence count and cross-references

---

### Layer 2: Project Rules → Evidence-Backed Entities

**Current:** Markdown file `.crabcakes/coder-rules.md`. Rules are text with no provenance.

**Enhanced:** Rules are entities with `evidence` edges to supporting bug nodes. Rules have confidence, decay scores, and provenance.

**Example rule entity:**
```json
{
  "name": "rule_check-mock-type",
  "entityType": "rule",
  "observations": [
    "Never check truthiness on mock objects — always use isinstance()",
    "Evidence_count: 7",
    "Confidence: 0.94",
    "First_observed: 2026-01-15",
    "Last_confirmed: 2026-05-20",
    "Source: Qaster review + coder self-audit",
    "Decay_score: 0.23 (low — still very relevant)"
  ]
}
```

**Edges created:**
- rule_check-mock-type `evidence` bug_042
- rule_check-mock-type `evidence` bug_017
- rule_check-mock-type `evidence` bug_038
- rule_check-mock-type `injects_into` coder.md (via dream layer)
- rule_check-mock-type `test_coverage` test_watcher.py

**What becomes possible:**
- Rules are verifiable: check if the underlying evidence nodes still exist before applying
- Rules have provenance: where they came from, how validated, by whom
- Rules can be promoted to universal (all agents) when evidence_count exceeds threshold
- Rules with high decay scores can be auto-archived but kept queryable

---

### Layer 3: Auto-Test Enforcement → Causal Graph

**Current:** `enforcement.py` runs tests, appends pass/fail to tool output. Flat.

**Enhanced:** Every test run is a node. Results link to the code change that triggered it and the bugs it exposed.

**Example test_run node:**
```json
{
  "name": "test_run_2026-05-26T14:32",
  "entityType": "test_run",
  "observations": [
    "triggered_by: write_file to watcher.py",
    "test_file: tests/test_watcher.py",
    "result: 2 failures, 3 passes",
    "duration_ms: 847",
    "linked_to: [bug_051, bug_052]"
  ]
}
```

**Edges created:**
- test_run_2026-05-26T14:32 `triggered_by` watcher.py_write_2026-05-26
- test_run_2026-05-26T14:32 `exposed` bug_051
- test_run_2026-05-26T14:32 `exposed` bug_052

**What becomes possible:**
- Blast radius query: "changing `_emit_moved` affects 4 test files, 3 of which failed in the last 30 days"
- Historical pattern: "Every time `_handle_rename` is modified, test_watcher.py breaks within 1 day" — emerges from graph topology, not human observation
- Test quality scoring: which tests consistently catch real bugs vs. which produce false positives
- Auto-link test failures to code changes and bug nodes — the chain from write to failure to bug is traceable

---

### Layer 4: Structured Feedback → Traceable Cause Chains

**Current:** Audit reports in flat files, manually converted to bug journal entries.

**Enhanced:** Audit findings auto-populate the graph. Every finding is a node linked to its source audit, the code change it targets, and the pattern it exemplifies.

**Example audit node:**
```json
{
  "name": "audit_Qaster_PR47_2026-05-26",
  "entityType": "audit",
  "observations": [
    "Reviewer: Qaster",
    "Target: watcher.py changes in PR #47",
    "Findings: 1 bug, 1 design issue",
    "Severity: bug"
  ]
}
```

**Auto-population flow:**
1. Reviewer (Qaster or another agent) submits audit report
2. `audit_parser.py` parses the report
3. `feedback_processor.py` creates audit node + finding nodes
4. Finding nodes automatically link to relevant bug nodes or create new ones
5. Pattern nodes receive new `observed_in` edges if the finding matches an existing pattern

**What becomes possible:**
- Every audit finding auto-populates the bug journal via typed edges
- Cross-reviewer compounding: if 3 reviewers flag the same pattern, its confidence climbs
- The graph connects design issues to root causes: "this design issue is the same root cause as bug #31 from 4 months ago"

---

### Layer 5: Dream Consolidation → Graph Analytics

**Current:** Cron runs LLM analysis on flat bug journal markdown. Text processing on a flat file.

**Enhanced:** Cron runs LLM analysis on graph structure. The LLM queries the graph, not the text.

**What it queries:**

```python
# Example: pattern clustering
query = """
Find all pattern nodes where observed_in has more than 5 bugs
and no same_pattern_as edges between them.
Create same_pattern_as edges between those bugs.
"""
```

```python
# Example: rule promotion
query = """
Find all rule nodes where evidence_count >= 10
and confidence >= 0.90
and not marked as universal.
Mark for promotion to universal_agent_rules.
"""
```

```python
# Example: blast radius warning
query = """
Find all code_change nodes in the last 7 days.
For each, traverse affected edges to find file_entity nodes.
For each file_entity, find all bug nodes connected via was_fixed_by.
If any bug has confidence >= 0.85 and was_fixed_by is recent,
warn: high-risk file proximity.
"""
```

```python
# Example: hypothesis generation
query = """
Find all bug nodes where the preceding tool sequence
contained read_file before write_file.
Count: X bugs.
Find all bug nodes where write_file came without preceding read_file.
Count: Y bugs.
If X < Y with statistical significance,
hypothesis: agents who read before write have fewer bugs.
Promote to rule: always_read_before_write.
"""
```

**Cron schedule:** Nightly at 2 AM (after daily work, before morning standup). Analyzes graph changes from the day. Outputs a `dream_report.md` that Coder reads on startup.

**Dream report structure:**
```markdown
# Dream Report — 2026-05-26

## New patterns detected
- abstraction-leak: appeared 3 times this week, all in handler classes

## Rule promotions
- check-mock-type: promoted from coder-specific to universal (12 evidence, 0.94 confidence)

## Blast radius warnings
- session_handler.py: 8 bug nodes connected, 3 active this month — review recommended

## Hypothesis
- "Agents who use read_file before write_file have 40% fewer bugs" (47 vs 78 in dataset)
- Confidence: 0.87 — recommend encoding as enforcement rule

## Decay warnings
- rule_session-timeout-check: confidence dropped from 0.81 to 0.54 this month — evidence stale
```

---

## Key Design Decisions

### Graph is a Read/Write Layer, Not a Replacement

The flat files (`.crabcakes/coder-bugs.md`, `coder-rules.md`) stay as the **source of truth** and **human-readable backup**. The graph is an **index** on top — write goes to file AND to graph. If the graph is ever wiped, it rebuilds from the files.

### Schema Migration is One-Way, Then Living

Initial migration: scan existing flat files, create graph nodes and edges. After migration, the graph is the primary store. Flat files become export-only.

### Tool Namespacing Convention

All MCP tools are namespaced: `memory/create_entities`, `memory/search_nodes`, etc. CrabCakes graph operations use:
- `graph/create_node` — create any CrabCakes-specific node type
- `graph/create_relation` — create typed edges
- `graph/search` — semantic search across all node types
- `graph/read_subgraph` — get a neighborhood around a node
- `graph/update_observations` — add/update observations on existing nodes

### Decay Model

```
decay_score = f(recency, evidence_count, cross_reference_count, query_frequency)
- Frequently queried nodes → decay slower
- Many cross-references → decay slower
- No new evidence in 30+ days → decay faster
- Very low decay → archive but keep queryable
```

---

## What Already Works (No New MCP Infrastructure Needed)

| Component | Status |
|-----------|--------|
| MCP stdio transport | ✅ Working |
| `create_entities` / `create_relations` / `search_nodes` / `read_graph` | ✅ Verified |
| Per-agent MCP config via YAML | ✅ Working |
| Hot-reload on agent save | ✅ Via existing `_on_agent_saved()` |
| Tool merge into agent tool list | ✅ Via `get_tools_for_api()` |

---

## What Needs to Be Built

| Component | File | Effort |
|-----------|------|--------|
| CrabCakes graph schema definitions | `utils/graph_schema.py` | ~100 lines |
| `graph/create_node` tool wrapper | `utils/graph_tools.py` | ~80 lines |
| Layer 1 migration: flat bugs → graph nodes | `utils/migration.py` | ~150 lines |
| Layer 3 wiring: test_run nodes from enforcement.py | `agent/enforcement.py` | ~40 lines |
| Layer 4 wiring: audit → graph auto-population | `utils/feedback_processor.py` | ~120 lines |
| Layer 5 dream cron job | `utils/dream_consolidation.py` | ~200 lines |
| Dream report → Coder system prompt injection | `utils/prompt_loader.py` | ~20 lines |

**Total:** ~710 lines across 7 files.

---

## Status

- [ ] Schema design approval
- [ ] Graph schema definitions
- [ ] Graph tool wrappers
- [ ] Layer 1 migration script
- [ ] Layer 3 test_run wiring
- [ ] Layer 4 audit auto-population
- [ ] Layer 5 dream cron + report
- [ ] Integration test (full chain)
- [ ] Push to GitHub