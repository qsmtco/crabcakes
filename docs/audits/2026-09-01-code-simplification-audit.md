# Code Simplification Audit — 2026-09-01

**Scope:** Full production tree (`agent/`, `ui/`, `models/`, `gateway/`, `utils/`, `scripts/`, `main.py`, repo root). Tests excluded except where they keep dead code alive.
**Method:** Four parallel deep analyses (one per area) plus cross-cutting checks. Every dead-code claim verified by repo-wide grep or AST import analysis. Read-only — no code was modified.
**Reviewers:** 4 analysis passes + 1 cross-cutting pass.

---

## Executive Summary

| Area | LOC | Est. reduction | Headline |
|---|---|---|---|
| `agent/` | 10,275 | **600–800** | `_run_loop` (683 lines) decomposition; dead provider-dispatch remnants |
| `ui/` | 29,337 | **~850** | 3 near-identical bubble builders; `MainWindow._build` (775 lines); `on_send` (313 lines) |
| `utils/` | 9,883 | **~300** | 4 cross-file duplicate helpers; dead `get_recent_commits`; `format_markdown` split |
| `models/` + `gateway/` + `scripts/` | 3,721 | **~1,150** | ~1,016 LOC of verified dead code (deprecated task system, broken audit scripts) |
| Repo root scratch scripts | 591 | **591** | 18 one-off extract/find/read/diagnose scripts, all throwaway |
| **Total** | ~53,800 prod | **~3,500–3,700 (~7%)** | |

Plus ~200–400 lines of test code that only exercises dead shims.

---

## 1. Cross-cutting findings (repo-wide)

- **[P1] 18 root-level scratch scripts (591 LOC)** — `_audit_verify.py`, `_verify_phase1.py`, `_test_htmlescape.py`, `diagnose_drawer_gap.py`, `inspect_filetree_drawer.py`, `extract_{sections,context,architecture,prompt_section,window_lines,create_project}.py`, `find_{inventory,lines,section}.py`, `read_{arch_section,bytes,section}.py`. All one-off diagnostics; none imported anywhere. → Delete or move to `scripts/archive/`.
- **[P1] Deprecated task system still fully present** — `models/task.py` banner says "DEPRECATED: superseded by models/work_unit.py". Commands route to `WorkHandler` (`command_handler.py:108-122`). `TaskHandler` (`ui/handlers/task_handler.py`, 358 LOC) is **never instantiated**; confirmed orphan via AST import analysis (only module in `agent/ui/models/utils` whose name appears in no other file's imports). → Delete `models/task.py` (108) + `ui/handlers/task_handler.py` (358) + `task_store` singleton in `models/__init__.py:29`.
- **[P3] Debt markers**: 136 `TODO/FIXME/HACK/XXX` + 201 `LOW-N`/`HIGH-N` audit-marker comments. The `LOW-N`/`HIGH-N` series reads like leftovers from a completed security audit — worth triaging and stripping the resolved ones.
- **[P3] 29 swallowed `except Exception: pass`** across `agent/ui/models/utils` — each silently eats a failure. Triage: narrow, log, or delete.
- **[P3] Git history shows `Accept: 20 files (...)` commits** — automated bulk-accept flow. Not a code issue, but explains how scratch scripts accumulate in the repo root.

---

## 2. `agent/` (24 files, 10,275 LOC)

### P1 — Dead code (all grep-verified)

| # | Location | What | LOC |
|---|---|---|---|
| 1 | `runtime.py:2148-2156`, `2713-2718` | `caller = _PROVIDER_CALLERS.get(...)` bound + None-checked but **never invoked** (dispatch actually goes through `_get_provider(caller_key).call(...)`) | −12 |
| 2 | `runtime.py:216-220` | `_PROVIDER_CALLERS` dict is now a key set: `.call` never invoked; only `.keys()`/`.get()` used. → `frozenset`; also drops 5 provider instantiations at import time | −8 |
| 3 | `runtime.py:1799` | `workspace = resolve_session_workspace(...)` computed, never used; runs `os.makedirs(0o700)` + regex **on every tool call** | −3 |
| 4 | `runtime.py:564, 592-594` | `self._approval_callback` + `set_approval_callback` — set, never read, no callers repo-wide | −8 |
| 5 | `runtime.py:16-32, 190-278` | Unused imports: `re`, `time`, `Iterator`, `AuditEntry`, `convert_*_for_anthropic`, 4 SSL-retry constants, `urllib.error/request` | −18 |
| 6 | `enforcement.py:124-138` | `DEFAULT_SKIP_PATTERNS` — dead; real default lives in `EnforcementConfig.skip_patterns` (`config.py:56-65`) | −16 |
| 7 | `context.py:694-715` | `_load_crabcakes_doc` — own docstring: "Currently unused but kept for API completeness". No external importers | −22 |

### P2 — Duplication

- **`runtime.py:1745-1780`** — two approval-denial branches 90% identical (exec_command vs sensitive-path write). → `_deny_tool_call(...)` helper. **−20**
- **`runtime.py:2278-2331`** — tool-call assembly duplicated in `done` and fallback branches of `_call_llm_streaming`. → `_assemble_tool_calls(...)`. **−18**
- **`runtime.py:2020-2170` vs `2674-2744`** — `_call_for_summary` re-implements `_call_llm`'s provider dispatch (~50 lines overlap). → shared `_dispatch_non_streaming(...)`. **−30**
- **`runtime.py:2140-2170`** — two identical `except (IndexError, KeyError, TypeError, ValueError)` context-annotation wrappers. → hoist one. **−12**
- **`runtime.py:1532-1579` + `1638-1676`** — identical 16-line "build error_text from stream_err" blocks. → `_handle_stream_error(...)`. **−25**
- **`llm/openai_provider.py:133-186` vs `llm/minimax_provider.py:188-244`** — 90% identical SSE stream loops; MiniMax factored `_handle_finish_frame`, OpenAI inlined it. → promote to `streaming.py`. **−30**
- **`llm/streaming.py:298-342` (+ `348-440`)** — three near-identical retry/backoff blocks in `urlopen_with_ssl_retry` and `stream_with_ssl_retry`. → `_backoff(...)` helper. **−18**
- **`runtime.py:53, 263-268`** — 14 streaming re-imports mostly dead (`friendly_error_message` imported directly by `agent_runtime_handler.py`). **−15**
- **`enforcement.py:54-66`** — `_get_scrubbed_env` is a documented 3-line alias for `utils.env_security.get_scrubbed_env` (2 callers). → inline import. **−15**
- **`enforcement.py:303-391` vs `752-820`** — `_check_syntax`/`_check_lint` same shape (gate → argv → subprocess+scrubbed env → timeout → EnforcementCheck). → shared `_run_check(...)`. **−25**

### P2/P3 — Big-function decomposition

- **`runtime.py:1231-1910` — `_run_loop` is 683 lines, ~7 nested concerns.** Extract `_setup_turn`, `_process_text_response`, `_execute_tool_call`. **−150 to −200**, biggest single readability win in the repo.
- `context_strategy.py:679-732` vs `803-866` — two `_summary` implementations share transcript-building loop. → `_build_transcript(...)`. **−15**

### P3 — Notable

- `runtime.py:2354` `_check_stuck` history entries store unused `iteration` key.
- `runtime.py:1395, 1412` — function-scope imports in hot tool loop; hoist.
- `runtime.py:1131-1141` — `_compute_compaction_threshold` catches ALL exceptions (hides programmer bugs); narrow.
- `audit.py` — `AuditLog` grows unbounded in production; `flush_audit_log()` only called by tests. Wire to conversation-end or document. ⚠️ *Not a LOC issue — a slow memory leak.*

**Area total: ~600–800 LOC.** Top 3: `_run_loop` decomposition; `_call_llm`↔`_call_for_summary` unification (+70); dead-code sweep (~40, zero risk).

---

## 3. `ui/` (51 files, 29,337 LOC)

### God-files / god-methods

| File | LOC | Worst functions |
|---|---|---|
| `views/file_tree.py` | 2,391 | `__init__` 145, `_build_drawer_content` 131 |
| `handlers/feed_handler.py` | 1,896 | `on_project_opened` 151 |
| `handlers/agent_runtime_handler.py` | 1,887 | `_do_response_complete` 150 |
| `views/styles.py` | 1,667 | ~1,650 lines of static CSS |
| `window.py` | 1,651 | **`_build` 775 lines** |
| `views/chat_bubble.py` | 1,118 | `build_role_bubble` 134; `_process_text_chunk` 327 |
| `handlers/chat_handler.py` | 795 | **`on_send` 313 lines** |

### P1 — Dead code (grep-verified)

- `views/file_tree.py:1955` `_update_drawer_prefix` — no-op, zero call sites. **−5**
- `handlers/feed_handler.py:11,29` — unused imports (`dataclass`, `ConversationSnapshot`). **−2**
- `handlers/agent_runtime_handler.py:23` — top-level `FeedCardData` import unused (nested functions re-import locally). **−1**
- `handlers/agent_runtime_handler.py:106-111` — `_session_completed` redundant with `_ended_sessions`. **−6**
- `views/feed_tab.py:626` `_on_auto_accept_toggled` — docstring admits "effectively dead code on real FeedTab".
- **`handlers/feed_handler.py:195-278` — legacy v1 auto-accept paths (~85 LOC)** kept only for tests; v2 supersedes. **−85**

### P1 — Copy-paste duplication

- **Three near-identical bubble constructors**: `chat_bubble.py:build_role_bubble` ≈ `chat_render_handler.py:_assemble_from_processed` ≈ `chat_render_handler.py:_render_plain_text`. Same container/halign/css/header/content/buttons shape. Bonus: they've already drifted (`_assemble_from_processed` doesn't set `container._crabcakes_role/_text`, which bites snapshot extraction). → one `_build_bubble(role, agent_color, agent_name, body_builder)`. **~−270**
- **`chat_handler.py:on_send` (313 lines)** — 6 branches repeat the same render-echo + closure + routing. → `_render_echo(role, text)` + `_route_to_target(target, text)`. **~−120**
- **4 near-identical event cards** in `chat_bubble.py:880-1063`: `create_file_card`/`create_edit_card`/`create_tool_card`/`create_error_bubble` differ only in icon/label/content. → `create_event_card(icon, title, content)`. **~−120**
- **`feed_handler.py` `build_feed_card` approval-vs-non-approval block repeated verbatim ×5** (L746, 868, 991, 1167, 1284). → `_make_card_widget(...)`. **~−45**
- **`file_tree.py:346-430`** — 3 near-identical `Gtk.SignalListItemFactory` subclasses (`Status`/`Size`/`Modified`) differing only in property/css/xalign. → parameterized `LabelFactory`. **~−70** (+30 more via shared base with `FileTreeFactory`).

### P2 — Repeated boilerplate

- **`styles.py:380-470`** — 10 agent-color CSS blocks ×9 lines + 10 dot rules ≈ 100 LOC of template-able CSS. → generate from hex list. **−90**
- **`styles.py:1078-1106`** — 9 `.feed-card-<type>` header/body blocks. → generate from dict. **−30**
- **`Pango.parse_markup` guard repeated ×5** (chat_bubble:396, file_tree:222+1105, feed_card:148+341). → `safe_set_markup(label, markup, fallback)` in `utils/escaping.py`. **−15**
- **Transient copy-status ×2** (`file_tree.py:2371` vs `left_panel.py:986` — same 2.5s `GLib.timeout_add` pattern). → `utils/transient_status.py`. **−30**
- **Clipboard set ×5** (chat_bubble:1065, file_tree:1948+2365, left_panel:980, feed_handler:1581, diff_viewer:516). → `utils/clipboard.py::copy_to_clipboard`. **−25**
- **`activity_handler.py:on_gateway_event`** — `_resolve_agent_name(payload)` called 6× with same payload (L333-470). Hoist once.
- **Diff-loading pipeline ×2** (`file_tree._load_drawer_diff` ≈ `diff_viewer._load_current_diff` — same race-id + thread + `idle_add`). → `utils/diff_loading.py`. **−60**

### P3 — Other

- `chat_render_handler.py:_ReentrancySet` (24 LOC) wraps a set for one caller → plain `set[str]`. **−22**
- `feed_handler.py:1813` `add_audit_report_card` (65 LOC) is pure `FeedCardData` construction → move to `models/feed_card.py`. **−30**
- `agent_runtime_handler.py:1078` `_on_tool_call_start` (93 LOC switch on tool_name) → renderer dict. **−25**

**Area total: ~700–750 LOC mechanical + ~120 dead/legacy ≈ 850.** Top 3: split `_build` (pure refactor, huge cognitive win); collapse 3 bubble builders + 4 card factories (~390); generate styles.py color CSS + 3 shared helpers (~190).

---

## 4. `utils/` (39 files, 9,883 LOC)

Method note: every public/private function grep-verified across all 281 .py files.

### P1 — Cross-file duplication (diff-verified)

- **`_atomic_write_json` / `_atomic_write_text` duplicated**: `feed_store.py:30-55` (with chmod 0o600/0o644) vs `work_persistence.py:83-96` (no chmod) — byte-identical otherwise. Silent divergence trap. → one helper with `chmod_mode: int | None` arg. **−25**
- **`_NoAuthRedirectHandler` byte-identical in 2 files**: `improve.py:17-32` ≡ `provider_test.py:32-47` (diff-verified). → shared `utils/http_helpers.py`. **−20**
- **`_ensure_crabcakes_dir` reimplemented with different semantics**: `project_awareness.py:102` raises on `.crabcakes`-as-file; `feed_store.py:89` silently makedirs. → reuse one helper. **−8**
- **Two prompt-directory scanners compute the same path**: `prompts.py:6` `PROMPTS_DIR` ≡ `prompt_paths.py:18` `APP_USER_PROMPTS_DIR` (runtime-verified both resolve to `<repo>/prompts`); `prompts.load_prompts` vs `agent_defs.get_available_prompts` overlap. → delete `utils/prompts.py`, use `prompt_paths`. **−30, −1 file**

### P1 — Dead code

- **`git_ops.py:228` `get_recent_commits`** — zero callers repo-wide; duplicates `log` (L215). **−22**

### P2 — Architectural overlap

- **`project_awareness.py:887` `build_awareness_block` vs `:1033` `build_awareness_dict`** — ~60% duplicate string-assembly; only return shape differs. → shared `_compute_awareness_components(path)`. **−60 to −80**
- **`git_ops.py:359` `status_porcelain`** — 44-line subprocess workaround for a GitPython subdirectory bug; `status()` (L336) already returns the same porcelain text. → parse GitPython output. **−44**
- **`provider_test.py` (307 LOC)** mirrors `agent/runtime.py` request shapes. If runtime exposed `do_minimal_test(provider_config)`, file shrinks ~60-70%.
- *(overlaps agent/ finding: `enforcement._get_scrubbed_env` alias — counted once in §2.)*

### P3 — Long functions

- **`markdown.py:81` `format_markdown` (287)** — 7-step pipeline already delimited by `# ── Step N ──` comments; lift each step to `_stepN_*`. **−80 to −100**
- **`prompt_loader.py:146` `compose_system_prompt` (235)** — 7 numbered load+append sections → `_add_identity`, `_add_project_context`, `_add_review_mode`, `_add_role`, `_add_self_improvement`; body becomes ~40 LOC orchestrator.
- **`escaping.py:115` `escape_for_pango` (174, 6 nesting levels)** — extract `_emit_known_tag(...)` (~80 LOC block) + `_close_orphans(...)`.
- **`diff_parser.py:124` `_parse_file_block` (164)** — extract `_extract_header` + `_parse_hunks`; body → ~30 LOC.
- **`stt.py:49` `STTEngine`** — `stop_async` duplicates `stop`'s drain→transcribe→callback body. → `_drain_and_transcribe(frames)`.
- **`icons.py`** — `render_folder_icon` (92) vs `render_agent_icon` (62): identical scaffolding + duplicate inner `_darken` + suspicious `__import__('re')` at L23. → `_render_svg_to_texture(svg, size)` + module-level `_darken`. **−50**
- `spellcheck.py:42,86` — `check_words`/`get_suggestions` duplicate subprocess shell → `_run_enchant(mode, text, dict_path)`. **−20**
- `feedback_processor.py:123` `append_to_bug_journal` (101, 5-level nesting) — 3-4 concerns → helpers. **−40**

**Area total: ~300 LOC reduction + major readability wins.**

---

## 5. `models/` + `gateway/` + `scripts/` + `main.py` (3,721 LOC)

### P1 — Dead / broken (verified)

| Location | What | LOC |
|---|---|---|
| `scripts/audit_attack_scenarios.py` | **Broken on import** — imports removed `agent.runtime._PROVIDER_STREAMERS`; zero references | −128 |
| `scripts/audit_streaming_scenarios.py` | Likely broken (patches stale surface), unused, try/except swallows real bugs | −287 |
| `models/task.py` + `ui/handlers/task_handler.py` | Deprecated task system (see §1) | −466 |
| `models/colors.py:127-149` `hex_to_rgb` | Zero callers | −23 |
| `models/colors.py:110-125` `all_palette_css_classes` | Zero callers | −16 |
| `models/conversation.py:404-470` shims | `trim_to_token_limit` + `_last_exchange_summary` — deprecated, violate models→agent layer rule, only tests call them | −66 (+~200 test LOC) |
| `gateway/client.py:42, 421-450` | `send_message(on_sent=...)` — no caller passes it; 2-arg callback would violate its own annotation if ever called | −30 |
| `main.py:55-60` | 6 trailing "test change" dev comments | −6 |
| `scripts/bulk_repair_empty_assistant.py` | One-shot 2026-07-05 migration, confirmed complete by post-mortem → archive | −194 |

### P2 — Duplication / layer leaks

- **`models/providers.py:40-56` `ProviderConfig` vs `agent/config.py:29-43` `LLMProviderConfig`** — near-identical 11-field dataclasses + runtime 1:1 converter `_to_llm_provider` (`agent/config.py:132-145`). → keep `ProviderConfig`, import directly. **−50**
- **`models/activity.py:203-249` vs `ui/views/activity_drawer.py:26-52`** — `_type_label`/`_format_duration` duplicated with "keep in sync" comments… **and already drifted** (drawer omits `lifecycle_end`/`tool_*` mappings + None guard). → import from `models/activity.py`; fixes latent bug. **−25**
- **`models/conversation.py`** — tiktoken iteration loop duplicated between `_count_tokens_accurate` and `get_token_breakdown`. → `_iter_token_buckets(encoding)`. **−20**
- **`gateway/client.py:76-211` `_load_identity` (136 LOC)** — 5 nested try/excepts, 3 fallback paths. → 4 helpers; shrinks to ~25 LOC.
- **`gateway/client.py:489-577` `_handshake` (90 LOC)** → extract `_build_v3_signature` + `_build_connect_request`. **−30**
- **`models/agents.py:1-60` `AgentManager`** — 60-line class over 3 dicts; `get_names_ref()` leaks internal dict. → `@dataclass AgentState` or module dicts. **−40**
- **`models/feed_card.py:91-119`** — `is_actionable`/`is_informational` overlapping logic; `ui/views/feed_card.py:441` computes `is_informational` into a **dead local**. → collapse to one `kind()` + drop dead local. **−30**

### P3

- `gateway/client.py:516-525` — magic protocol numbers `minProtocol=3, maxProtocol=4`, version `"2026.5.14"` → named constants.
- `models/providers.py:21-37` — `CALLER_DEFAULT_MAX_TOKENS`/`_VALID_CALLERS` duplicated into `utils/providers_store.py` (layer-rule forced, test-enforced) → hoist both to `models/` and import from there.
- `models/conversation.py:141-184` — `Conversation` dataclass carries 7 audit-only config fields (`app_title`, `fallback_*`, `si_enforcement`, `provider`, `api_key`, `mcp_servers`, `allowed_tools`) → split to `AgentMetadata`. ~20 fields → ~10.
- `models/colors.py:45-66` — special-agent colors share the regular agent counter (surprising but tested); document or split.
- `models/feed_card.py:128-134` — `_serialize_metadata_with_snapshot` used once → inline into `to_dict`. **−7**

**Area total: ~1,150 LOC (~31% of in-scope LOC).** Top 3: dead-code sweep (−1,016); collapse `LLMProviderConfig` (−50 + removes a layer leak); de-duplicate drifted `_type_label`/`_format_duration` (−25 + fixes drift bug).

---

## 6. Top 10 actions, ranked (impact × low risk)

1. **Delete the verified-dead corpus** (~2,000 LOC): root scratch scripts (591), task system (466 + task_store), broken audit scripts (415), conversation shims (66 + their tests), `colors.py` helpers (39), `main.py` comments (6), `on_sent` callback (30), `get_recent_commits` (22), agent/ dead items in §2-P1 (~87), ui/ dead items in §3-P1 (~99).
2. **Split `MainWindow._build` (775)** → `_build_chat_stack` / `_build_sidebar` / `_build_settings_pane` / `_wire_handlers`. Pure mechanical, ~0 net LOC, massive reviewability win.
3. **Split `_run_loop` (683)** → `_setup_turn` / `_process_text_response` / `_execute_tool_call`. −150 to −200.
4. **Collapse 3 bubble builders + 4 event-card factories** in chat rendering. ~−390 and kills an existing drift bug.
5. **Unify `_call_llm` ↔ `_call_for_summary`** dispatch + dead `caller` checks + duplicated error/denial blocks in `runtime.py`. ~−120.
6. **Collapse `LLMProviderConfig` into `ProviderConfig`**; delete `_to_llm_provider`. −50, removes a cross-layer dataclass twin.
7. **Extract 4 shared ui helpers**: `safe_set_markup`, `copy_to_clipboard`, `transient_status`, `diff_loading`. ~−130 and prevents the next 5 copies.
8. **Generate `styles.py` color CSS** from data. −120.
9. **utils dedup**: atomic-write helpers, `_NoAuthRedirectHandler`, `.crabcakes` dir helper, prompt-dir scanners, `build_awareness_*`. ~−180.
10. **De-duplicate the drifted `_type_label`/`_format_duration`** (models/activity ↔ ui/activity_drawer) — small LOC, fixes a live divergence bug.

---

## Caveats

- LOC estimates are from the analysis passes; each dead-code claim was grep-verified, but **deletions should still go through the test suite** (`tests/` is 57k LOC and some of it exercises the deprecated shims — those tests go too).
- `_run_loop` and `_build` decompositions are behavior-preserving refactors but touch state machines — do them one extraction at a time with the existing test coverage.
- The `LOW-N`/`HIGH-N` comment series (201 occurrences) suggests a completed security audit; confirm before stripping.
- `AuditLog` unbounded growth (§2 P3) is flagged separately as a potential slow leak, not a LOC item.

*Generated 2026-09-01 by 4 parallel deep-analysis passes + cross-cutting verification. Read-only audit; no source files were modified.*
