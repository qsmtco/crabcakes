# Dead Code Audit — crabcakes

**Date:** 2026-09-01 (America/Los_Angeles)
**Scope:** ~298 Python files, ~111k lines (`agent/`, `chat/`, `gateway/`, `knowledge/`, `models/`, `ui/`, `utils/`, `scripts/`, root)
**Tooling:** vulture 2.16 + pyflakes 3.4 (run from a throwaway `/tmp` venv; project code untouched)
**Raw outputs:** `vulture-60.txt` (min-confidence 60, 190 findings), `vulture-80.txt` (min-confidence 80, 15 findings) in this directory

> Note: findings were gathered across interrupted runs; line numbers may drift if the tree changes.

## 1. Dead root-level one-off scripts (17 files, zero references)

Scratch/debug utilities, unreferenced by any other file:

- `_audit_verify.py`
- `diagnose_drawer_gap.py`
- `extract_architecture.py`
- `extract_context.py`
- `extract_create_project.py`
- `extract_prompt_section.py`
- `extract_sections.py`
- `extract_window_lines.py`
- `find_inventory.py`
- `find_lines.py`
- `find_section.py`
- `inspect_filetree_drawer.py`
- `read_arch_section.py`
- `read_bytes.py`
- `read_section.py`
- `_test_htmlescape.py`
- `_verify_phase1.py`

## 2. Confirmed-dead functions (vulture flagged + verified zero call sites)

- `agent/context.py:694` — `_load_crabcakes_doc()`
- `models/colors.py:110` — `all_palette_css_classes()`
- `models/colors.py:127` — `hex_to_rgb()`
- `utils/git_ops.py:228` — `get_recent_commits()`
- `ui/views/session_menu.py:213` — `display_name_from_row()`
- `ui/views/chat_bubble.py:1113` — local `html_escape()` (duplicate of the utils version)
- `agent/kb_lookup.py:84` — `get_index_path()` (1 doc-only ref; recheck before deleting)
- `utils/git_ops.py:158` — `diff_stat_against()` (3 refs found post-flag; recheck — likely live)

### Vulture false positives (live code — do NOT delete)

These were flagged at 60% confidence but have real call sites:

- `set_approval_callback` (13 refs), `save_feed` (25), `append_project_context` (18), `summarize_diffstat` (15), `is_favorite` (11), `get_connected_servers` (5), `reset_cache` (3)

Treat the full 60%-confidence list as leads only, not verdicts.

## 3. Unused imports / locals (335 pyflakes hits)

Highlights:

- `agent/runtime.py` — large block of unused imports: `agent.llm.streaming.*` (lines ~190, 261: `sse_lines`, `parse_sse_line`, `parse_sse_delta`, `first_choice`, `urlopen_with_ssl_retry`, `is_retryable_ssl_error`, `friendly_error_message`, `RETRYABLE_SSL_ERRORS`, `RETRYABLE_OSERROR_TYPES`, `MAX_SSL_RETRIES`, `SSL_RETRY_BASE_MS`), `agent.llm.convert.*` (`convert_messages_for_anthropic`, `convert_tools_for_anthropic`), plus `re`, `time`, `urllib.request`, `AuditEntry`, `resolve_api_key_for_conversation`, `MessageRole`
- `agent/context.py` — `re`, `typing.Callable`; unused local `depth` (line 88)
- `agent/config.py` — `dataclasses`
- `agent/runtime.py` — unused locals `workspace` (1799), `tokens_after` (2659)
- `utils/project_awareness.py` — `get_projects_config_dir`
- `utils/syntax_highlight.py` — `get_lexer_for_filename`
- `ui/views/chat_bubble.py` — `_get_placeholder_index`, `is_crabcakes_placeholder`
- ~15 unused locals across `ui/views/file_tree.py`, `diff_viewer.py`, `feed_tab.py` (`pspec`, `lb`, `it`, `direction`, `scroll_window`, `listbox`, `column_view`, `other_file`, `anchored`)

## 4. Latent bugs (not dead code, but found during the audit)

- `agent/persistence.py:42,134` — `Conversation` is undefined (used in quoted annotation, never imported); raises `NameError` if annotations are evaluated
- `gateway/client.py:118` — undefined `logger`
- `ui/handlers/review_handler.py:299` — undefined `e` (outside except block)
- `ui/handlers/auxilium_wizard_handler.py:355` — undefined `ProviderConfig`
- `ui/handlers/command_handler.py:240` — undefined `MentionResolution`
- `ui/handlers/feed_handler.py:70,87,839,1243` — undefined `Gtk`; `:978` undefined `logger`
- `ui/handlers/chat_render_handler.py:281,314` — undefined `exc`; `:324` undefined `Callable`, `FeedCardData`
- `ui/views/left_panel.py:191,195,199` — undefined `FeedTab`
- `ui/views/settings_dialog.py:359` — undefined `SettingsHandler`
- `utils/mcp_config.py:51` — undefined `StdioServerParameters`
- `ui/handlers/feed_handler.py` / `ui/gtk_safe_link.py` — `Gtk` may be a GTK-optional import pattern; verify before treating as bugs
- `scripts/rebuild_kb_index.py:170` — `np` used without import

## Summary / recommended cleanup order

1. **Safest deletions:** the 17 root scratch scripts, the 6 confirmed-dead functions, unused imports
2. **Fix-first (bugs):** the undefined-name list in §4
3. **Housekeeping:** clean stale `agent/__pycache__` (contains .pyc for modules; also `knowledge/__pycache__`, `__pycache__` at root)
