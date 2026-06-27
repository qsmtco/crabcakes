# Architecture Consistency Audit — 2026-06-27

**Auditor:** Qaster
**Scope:** Full codebase vs `docs/ARCHITECTURE.md`
**Method:** Systematic grep + file inventory comparison + line-count verification + import-layering analysis
**Sub-agents:** 4 (file inventory, import violations, undocumented modules, stale line counts)

---

## Executive Summary

| Category | Count | Severity |
|----------|-------|----------|
| Undocumented production modules (§3 gaps) | 11 | MEDIUM — doc drift |
| Files missing from §2 directory tree | 15+ | MEDIUM — structural drift |
| Stale line counts in §13 | 11 of 12 checked | LOW — cosmetic |
| Import/layering violations (§2 rules) | 3 | MEDIUM — `utils/` imports GTK |
| Handler-to-handler import violations (§8.6) | 0 | ✅ Clean |
| Views importing handlers | 0 | ✅ Clean |
| gateway/ → ui/ violations | 0 | ✅ Clean |
| models/ → ui/ violations | 0 | ✅ Clean |
| agent/ → ui/ violations | 0 | ✅ Clean |
| Duplicate/mis-indented entries in §2/§13 tree | 2 | LOW — formatting |
| Ghost references (doc mentions non-existent files) | 0 | ✅ Clean |

**Overall:** The architecture's core invariants (layering, handler isolation, model purity) are intact. The gaps are almost entirely documentation drift — modules added without updating ARCHITECTURE.md per §0's "same commit" rule. The largest single gap is `agent/context_strategy.py` (598 lines, completely undocumented in §3).

---

## 1. Import / Layering Violations

### 1.1 `utils/` imports GTK (3 files) — MEDIUM

ARCHITECTURE.md §2 table says `utils/` = "Pure Python utilities — no GTK, no network." Three files violate this:

| File | Line | Import | Severity | Notes |
|------|------|--------|----------|-------|
| `utils/icons.py` | 19 | `from gi.repository import Gdk` (module-level) | MEDIUM | Icons need Gdk.Texture for SVG rendering. Has self-justifying comment ("utils/ is allowed GTK access") but §2 says otherwise. |
| `utils/gtk_safe_link.py` | 93 | `from gi.repository import Gtk, Pango` (lazy, inside function) | MEDIUM | Link validation needs to parse Pango markup. Self-justifying comment at top. |
| `utils/stt.py` | 135 | `from gi.repository import GLib` (lazy, inside thread callback) | LOW | Uses `GLib.idle_add` to marshal STT result back to main thread. Has `except ImportError` fallback. |

**Recommendation:** Either:
- **(A)** Move `icons.py` and `gtk_safe_link.py` to `ui/views/` or a new `ui/gtk_helpers/` package (they're GTK helpers, not pure utilities), and add a documented carve-out for `stt.py`'s lazy GLib import.
- **(B)** Amend ARCHITECTURE.md §2 to formally exempt these three files as "GTK helper exceptions" with a rationale.

### 1.2 All other layers clean ✅

| Check | Result |
|-------|--------|
| `gateway/` → `ui/` imports | **0 violations** |
| `models/` → `ui/` or GTK imports | **0 violations** |
| `agent/` → `ui/` or GTK imports | **0 violations** |
| `ui/handlers/` → another handler import | **0 violations** (§8.6 actively enforced — `agent_command_handler.py:544` has a comment: "Duplicated from ChatHandler because handlers cannot import each other") |
| `ui/views/` → `ui/handlers/` imports | **0 violations** |

---

## 2. Undocumented Production Modules (§3 Gaps)

These 11 production files exist in the codebase but have **no §3 entry** in ARCHITECTURE.md. Total undocumented code: **~2,305 lines**.

| # | File | Lines | What it does | Suggested §3 placement |
|---|------|-------|-------------|----------------------|
| 1 | `agent/context_strategy.py` | 598 | Pluggable context compaction strategy (P1–P7 algorithms, `ContextStrategy` protocol, `DefaultContextStrategy`, `CompactionEvent` telemetry). **Largest gap in the doc.** | New section near §3.21p (sibling to `agent/context.py`) |
| 2 | `utils/providers_store.py` | 415 | Provider config persistence — load/save `providers.yaml`, migrate from legacy `agent.json`, atomic writes. Referenced from §3.21q.5a but never documented standalone. | New section near §3.11b (provider config cluster) |
| 3 | `ui/handlers/settings_handler.py` | 231 | Settings dialog business logic — provider CRUD, test connection dispatch, status tracking. No §3 entry at all. | New section in handler cluster |
| 4 | `ui/views/settings_dialog.py` | 487 | Settings dialog GTK view — provider list, add/edit/remove, test connection button. No §3 entry. | New section paired with settings_handler |
| 5 | `utils/project_trust.py` | 203 | Project trust gate — path traversal prevention, symlink validation for agent file operations. Security-critical. | Sub-section of §3.27 (project_awareness cluster) |
| 6 | `ui/wiring.py` | 128 | Stateless wiring functions — `wire_settings_handler()`, env-var helpers. Mentioned briefly in §3.21u.a but not fully documented. | Expand §3.21u.a |
| 7 | `utils/gtk_safe_link.py` | 107 | Pango markup validation for user-supplied URLs/links. Security helper. | Sub-section near §3.14b (markdown cluster) |
| 8 | `utils/env_security.py` | 44 | Minimal environment dict for subprocess execution (strips dangerous env vars). | Sub-section near §3.21u (enforcement cluster) |
| 9 | `utils/file_security.py` | 36 | File path validation — path traversal prevention for agent writes. | Sub-section near §3.21w (mcp_config cluster) |
| 10 | `utils/provider_url.py` | 40 | Provider URL validation and normalization. | Sub-section near §3.11a (provider_test cluster) |
| 11 | `ui/constants.py` | 16 | Cross-cutting UI constants (`STREAMING_ENABLED` toggle). Shared between toolbar and ChatHandler without handler→handler import. | Merge into §3.4 or §3.5 |

**Note:** `agent/context_strategy.py` is the most significant gap — it's 598 lines of core compaction logic documented only in the spec (`SPEC-CONTEXT-MANAGEMENT-ROADMAP.md`), not in ARCHITECTURE.md. The post-mortem (§9 evolution suggestions) already flagged this.

---

## 3. §2 Directory Tree Drift

### 3.1 Missing top-level directories

§2's directory tree does not list these top-level directories that exist on disk:
- `scripts/` — contains `rebuild_kb_index.py`, `audit_attack_scenarios.py`, `audit_streaming_scenarios.py`
- `prompts/` — contains `prompts/system/` and `prompts/default_agents/` (§2 only references `prompts/system/` implicitly via `utils/prompt_loader.py`)
- `tests/` — 100 test files (§13 acknowledges this is "illustrative, not exhaustive")
- `docs/` — specs, post-mortems, audits, research

### 3.2 Missing files in §2's `agent/` tree

- `agent/context_strategy.py` — **598 lines**, completely missing from §2

### 3.3 Missing files in §2's `utils/` tree

These 7 files are missing from §2's directory tree (though some appear in §13):
- `utils/providers_store.py`
- `utils/provider_url.py`
- `utils/project_trust.py`
- `utils/gtk_safe_link.py`
- `utils/file_security.py`
- `utils/env_security.py`
- `utils/spellcheck.py` (present in §3.32 but missing from §2 tree)

### 3.4 Missing files in §2's `ui/` tree

- `ui/constants.py`
- `ui/wiring.py`
- `ui/handlers/settings_handler.py`
- `ui/views/settings_dialog.py`

### 3.5 Missing files in §2's `models/` tree

- `models/providers.py` — documented in §3.11b but absent from the §2 directory tree
- `models/streaming.py` — listed as a class symbol in §3.3 but absent from §2 tree

---

## 4. Stale Line Counts (§13 File Inventory)

11 of 12 checked file counts are stale. The `~` prefix means "approximate" but some deltas are significant.

| File | Doc says | Actual | Delta | Notes |
|------|---------|--------|-------|-------|
| `agent/runtime.py` | ~1420 | **2418** | **+998** (70%) | Biggest miss — context management, telemetry, streaming all added |
| `ui/styles.py` | ~1045 | **1245** | +200 | New CSS for feed cards, activity drawer, settings |
| `agent/tools.py` | ~892 | **1108** | +216 | MCP tools, security helpers |
| `ui/handlers/agent_runtime_handler.py` | ~867 | **1065** | +198 | Provider resolution, conversation restore |
| `ui/handlers/feed_handler.py` | ~932 | **1102** | +170 | Echo suppression, batch accept, audit reports |
| `ui/handlers/activity_handler.py` | ~610 | **767** | +157 | Activity drawer integration, recovery path |
| `ui/views/main_content.py` | ~857 | **942** | +85 | Scroll button, review bar |
| `ui/views/chat_bubble.py` | ~1015 | **1059** | +44 | Block headers, terminal segments |
| `ui/views/left_panel.py` | ~974 | **982** | +8 | Essentially current |
| `ui/handlers/chat_handler.py` | ~853 | **810** | **−43** | Doc overstates — logic extracted |
| `ui/handlers/chat_render_handler.py` | ~770 | **729** | **−41** | Doc overstates — logic extracted |
| `utils/project_awareness.py` | ~641 | **641** | **0** | ✅ Accurate |
| `ui/window.py` | ~693 | **957** | +264 | Window grew with new handler wiring |

---

## 5. Structural Issues in the Doc

### 5.1 Duplicate entries in §2/§13 tree

`connection_sync_handler.py` and `forward_handler.py` appear **twice** in the directory tree:

- **First occurrence** (§2, correct location, lines ~127-128): Properly listed under `ui/handlers/` with descriptions.
- **Second occurrence** (§13 tree, lines ~3542-3543): Mis-indented under `ui/views/` with shorter descriptions. Copy-paste artifact.

**Recommendation:** Delete the second (duplicate) entries in §13.

### 5.2 `ui/views/left_progress.py` — confirmed dead

§13 says "0 lines — stub placeholder." Confirmed: file exists and is genuinely 0 bytes (empty). Has been this way since April 10.

**Recommendation:** Delete the file and remove the §13 reference, or leave with a comment explaining the intent.

### 5.3 §2 missing `scripts/` directory

Three script files exist under `scripts/`:
- `scripts/rebuild_kb_index.py` — offline KB indexer
- `scripts/audit_attack_scenarios.py` — streaming security audit
- `scripts/audit_streaming_scenarios.py` — streaming audit helper

None are documented in §2 or §13.

---

## 6. What's Clean ✅

These findings confirm the architecture's core invariants are holding:

1. **Layering intact:** `gateway/`, `models/`, `agent/` have zero `ui/` imports. The foundation-only-upward rule holds.
2. **Handler isolation intact:** Zero handler-to-handler imports. §8.6 is actively enforced — `agent_command_handler.py` even has a comment documenting *why* it duplicates logic instead of importing from a peer.
3. **Views don't touch handlers:** Zero `ui/views/` → `ui/handlers/` imports. The callback-wiring pattern through `window.py` is working as designed.
4. **Models are pure data:** Zero GTK imports in `models/`. `StreamingBubble` uses `object` typed fields instead of GTK types — correct bridging pattern.
5. **No ghost references:** Every file mentioned in ARCHITECTURE.md exists on disk. No phantom modules.
6. **`models/providers.py` and `models/streaming.py`** both exist and match their documented APIs.
7. **`utils/project_awareness.py`** line count is exactly accurate (641 lines) — the only file in §13 that's still current.

---

## 7. Recommended Actions

### Priority 1 — Document undocumented modules (§0 violation)

Write §3 entries for all 11 undocumented production modules listed in §2. The most critical:
- `agent/context_strategy.py` (598 lines) — core compaction logic
- `utils/providers_store.py` (415 lines) — provider persistence
- `ui/handlers/settings_handler.py` + `ui/views/settings_dialog.py` (718 lines combined) — entire settings subsystem
- `utils/project_trust.py` (203 lines) — security-critical path validation

### Priority 2 — Resolve the `utils/` GTK import question

Either move `icons.py` and `gtk_safe_link.py` to a GTK-aware package, or formally amend ARCHITECTURE.md §2 to document the carve-out. `stt.py`'s lazy GLib import is arguably acceptable (it's a thread-dispatch mechanism, not a widget dependency) but should still be documented.

### Priority 3 — Update §2 directory tree

Add all missing files and directories to the §2 tree. Remove the duplicate entries in §13. Delete or annotate `left_progress.py`.

### Priority 4 — Refresh stale line counts in §13

Update all ~line counts in §13 to current values. Consider dropping the counts entirely (they'll always drift) or adding a "verified as of <commit>" annotation.

### Priority 5 — Add CI grep guard

Add a test or pre-commit hook that enforces the layering rules:
```bash
# Should return zero results
grep -rn "from ui" gateway/ models/ agent/
grep -rn "from gi.repository" models/ agent/
grep -rn "from ui.handlers" ui/views/
```

---

## Appendix: Audit Method

Four sub-agent audits ran in parallel:

| Audit | Scope | Runtime |
|-------|-------|---------|
| File inventory comparison | All `.py` files vs §2 + §13 | ~80s |
| Import/layering violations | grep-based check of all §2 layering rules | ~157s |
| Undocumented modules analysis | Read + classify 11 missing §3 entries | ~104s |
| Stale line count verification | `wc -l` on 12 files from §13 | ~59s |

Plus direct `grep`/`wc` verification by the supervising agent.
