# Spec — Security Remediation Phase 4 (12 Original-Review Findings Re-Shipped)

**Date:** 2026-06-19
**Author:** Qaster (implementation supervisor)
**Reviewer:** QTR (builder)
**Authority chain:** Captain's standing orders → `docs/ARCHITECTURE.md` (the floor) → this spec (narrows ARCHITECTURE.md for one feature) → the code (the artifact)

---

## 0. Why this spec exists

On 2026-06-19, an audit of working-tree changes against the original `docs/SECURITY_ARCHITECTURE_REVIEW.md` (commit `ca24246`) revealed that **12 original-review findings were silently dropped** from the Phase 0–3 remediation work. The Phase 3 spec (`docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md`) **re-bucketed the LOW-1..13 IDs** with a different set of items (Task user field, DELETE /agents, GET /agents, etc.) without reconciling the new IDs back to the original review's IDs.

The post-mortem (`docs/post-mortems/2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md`) inherited this drift and recorded "All Low except 0" shipped — true for the *Phase 3 re-bucketed LOWs*, false for the *original review's* LOWs.

**This spec re-ships the 12 original-review findings that were never actually addressed.** Every ID in this spec matches its corresponding ID in the original review. The "Phase 3 re-bucketed LOWs" stay where they are in the codebase; we are not re-bucketing again.

### 0.1 ID-stability rule (binding for this spec)

> Every finding ID in this spec, every phase-instructions file, every commit message, and every test added in this loop uses the **original review's finding ID**. The original review is the source of truth. A new finding introduced during implementation gets a new ID (e.g., `LOW-3.1` or `P4-NEW-1`), never a recycled ID.

---

## 1. Goals

Ship, in a single coordinated loop, **12 original-review findings** that were dropped from the Phase 0–3 work. Every shipped finding must be:
- (a) actually addressed in the code (verified by file:line + behavior)
- (b) covered by at least one test that fails without the fix and passes with it
- (c) mapped in a single per-finding table at the end of the loop, with commit SHAs

## 2. Non-goals

- Re-doing Phase 0–3 work
- Renaming or re-bucketing the "Phase 3 re-bucketed LOWs" — they are now part of the codebase under their own IDs and are not in scope
- Re-opening the deferred items (HIGH-2, HIGH-4, A-11) — those have explicit triggers in `docs/proposals/DEFERRED-ITEMS.md`
- Touching `agent/runtime.py`'s god-object structure (A-11 is deferred)
- Updating `docs/SECURITY_ARCHITECTURE_REVIEW.md` or `docs/THREAT_MODEL.md` — that paperwork is a separate pass after this loop is verified

## 3. Discovery — what I read before writing this spec

I read the following files in full to ground the spec in actual code, not memory:

| File | Why |
|---|---|
| `docs/ARCHITECTURE.md` (full) | Floor authority — what the spec must conform to |
| `docs/SECURITY_ARCHITECTURE_REVIEW.md` (full) | Source of truth for finding IDs and descriptions |
| `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md` (full) | The drifted Phase 3 spec — confirms the ID drift |
| `docs/post-mortems/2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md` (full) | Existing post-mortem — confirms the unverified "All Low shipped" claim |
| `docs/proposals/PROPOSAL-security-remediation-roadmap.md` (full) | Phasing intent |
| `agent/runtime.py:1150-1250, 1700-1740` | LOW-2 (file sandbox) and confirm atomic-write pattern exists for `tmp + os.replace` |
| `agent/runtime.py:1063-1066` | Reference for atomic-write pattern (already correct) |
| `gateway/client.py:188, 223, 281, 440, 447, 451-453, 506, 525-526` | LOW-3 (scopes), LOW-4 (raw logs), LOW-5 (event validation) |
| `utils/stt.py:1-167` (full) | LOW-6 (STT manifest + model-size env var) |
| `ui/views/chat_bubble.py:50-58, 558-570` | LOW-7 (xdg-open) |
| `utils/icons.py:79-156` (full) | LOW-8 (SVG escape) |
| `utils/git_ops.py:42-234` (full) | LOW-9 (raw str(e) GitPython errors — 15 sites) |
| `utils/diff_parser.py:144-152, 211-212, 226-227` | LOW-10 (lstrip char-set bug) |
| `utils/agent_defs.py:190, 345` | LOW-11 (load_agent_defs doesn't call validate_agent_def) |
| `utils/feed_store.py:122-128, 145-152` | LOW-12 (no .gitignore creation), LOW-13 (save_feed non-atomic) |
| `utils/image_utils.py` (full) | A-10 (zero importers) |
| `ui/views/left_panel.py:1-20` | A-10 (PromptsHandler import — was real, now fixed) |
| `utils/review_log.py:1-30, 19` | A-10 (dream_engine comment) |
| `ui/handlers/feed_handler.py:40-230` | A-10 (duplicate Remove column — was real, not currently present) |
| `tests/test_*.py` (file inventory, 100+ files) | Confirmed: no tests exist for the 12 unshipped findings |

## 4. The 12 findings — what each actually needs

For each finding: **ID**, **what the original review said**, **what the code actually looks like on HEAD** (with file:line), and **what the fix must do**. I verified every file:line below against the working tree.

### 4.1 LOW-2 — File tools default sandbox to `/tmp`

- **Original review:** "File tool execution should use a per-session temp directory under the project, not the world-writable `/tmp`."
- **HEAD reality (`agent/runtime.py:1722, 1736`):** `execute_tool(tool_name, args, conv.project_path or "/tmp", session_key, ...)` — falls back to `/tmp` when `project_path` is empty.
- **Fix:** Replace the `or "/tmp"` fallback with a per-session secure temp directory under `<project_path>/.crabcakes/tmp/<session_key>/` (created with `0o700` permissions). If `project_path` is empty, raise — never fall back to a world-writable path.
- **Test:** Call `execute_tool("write_file", ...)` with an empty `project_path` and assert the call is rejected with a clear error. Call with a valid `project_path` and assert the file lands under `.crabcakes/tmp/`, not `/tmp`.

### 4.2 LOW-3 — `operator.admin` scope as constructor parameter

- **Original review:** "Hardcoded `ALL_SCOPES = 'operator.admin,operator.approvals,operator.pairing'` should be a constructor param; request only the scopes the client actually uses."
- **HEAD reality (`gateway/client.py:188, 223, 440, 468`):** `ALL_SCOPES` is a module constant. `GatewayClient.__init__` does not accept a `scopes` parameter. The handshake always requests operator.admin.
- **Fix:** Add a `scopes: list[str] | None = None` parameter to `GatewayClient.__init__`. If `None`, default to `["operator.admin", "operator.approvals", "operator.pairing"]` (preserves current behavior). Pass through to the handshake at line 468. Document the constructor parameter in the class docstring.
- **Test:** Construct `GatewayClient(scopes=["operator.pairing"])`, assert the handshake payload contains only `operator.pairing`. Construct with `scopes=None`, assert it requests all three defaults (backward compatibility).

### 4.3 LOW-4 — Raw gateway log dump

- **Original review:** "Debug logs dump raw gateway frames up to 300 chars. This is fine at `CRABCAKES_GATEWAY_DEBUG=1` for developer debugging, but at default logging level it leaks JSON keys and partial payloads."
- **HEAD reality (`gateway/client.py:506, 525-526`):** `_logger.debug("[gateway>>] %s", raw[:300])` runs on every gateway message — at DEBUG level only. **However**, there is also a second `raw[:300]` mention at line 525 (malformed-JSON warning context) and `raw[:200]` at line 532 (malformed JSON decode warning). The issue is that when `CRABCAKES_GATEWAY_DEBUG=1` is set (the developer-debug env var), the log line fires unconditionally.
- **Re-scope:** The original review's concern is that raw frames leak at default logging level. Currently the log line is gated by `if os.environ.get("CRABCAKES_GATEWAY_DEBUG"): _logger.setLevel(logging.DEBUG)` at module load (lines 23-24). This is acceptable: it requires an explicit opt-in. However, two issues remain: (1) the malformed-JSON warning at line 525-526 also includes `raw[:200]` in the warning — this is unconditional and could leak data; (2) when the env var is set, EVERY raw frame logs — even frames that contain sensitive content (api keys, paths).
- **Fix:** (a) Truncate the malformed-JSON warning's `raw[:200]` to `raw[:80]` and rephrase to "malformed gateway message" (no inclusion of body). (b) Add a redaction pass before logging at line 506: replace common sensitive keys (`apiKey`, `token`, `password`, `deviceToken`) with `***` in the truncated preview.
- **Test:** Send a gateway message with `{"apiKey":"secret123", "other":"x"}`, assert that with `CRABCAKES_GATEWAY_DEBUG=1` the logged preview does NOT contain `secret123`. Send malformed JSON, assert the warning contains at most 80 chars of body.

### 4.4 LOW-5 — Unvalidated event payloads

- **Original review:** "`on_event(event_name, payload)` accepts any string and any dict. The chat handler crashes on malformed events."
- **HEAD reality (`gateway/client.py:451-453`):** `GLib.idle_add(self.on_event, evt_name, msg.get("payload", {}))` — passes event name and payload through with no type checks.
- **Fix:** Add a small `_validate_event(name, payload) -> bool` helper that:
  - rejects `name` if not a non-empty string
  - rejects `payload` if not a dict
  - allows a small known-event allowlist (chat final, agent start, agent end, etc.) through; other names are passed through (don't break unknown events) but logged at DEBUG
  - returns False on validation failure, in which case the event is dropped with a WARNING log
- **Test:** Call `_listen()` with `{"type":"event","event":"chat final","payload":"not-a-dict"}` and assert the event is dropped (no callback). Call with valid payload and assert it is dispatched. Call with `event=""` and assert it is dropped.

### 4.5 LOW-6 — STT manifest/network/model-size claim

- **Original review:** "STT code claims 'no network calls' in the manifest, but faster-whisper downloads model files on first load. Also, `STT_MODEL_SIZE` env var is honored without validation — a user could set it to `../../../etc/passwd` and we'd attempt to load a model from that path."
- **HEAD reality (`utils/stt.py:1-167`):** The manifest comment at line 16 says "no network calls" — false (faster-whisper downloads models). `STT_MODEL_SIZE` is read at line 58 with no validation. The model is loaded at line 161-167 by passing `self._model_size` directly to `WhisperModel(model_size, ...)`. faster-whisper resolves the name via Hugging Face Hub.
- **Fix:** (a) Update the security manifest at line 16 to accurately state: "Reads: ALSA device; Writes: none; Network: faster-whisper downloads model files on first transcription (one-time); External: Hugging Face Hub for model download". (b) Add `_VALID_MODEL_SIZES = {"tiny.en", "tiny", "base.en", "base", "small.en", "small", "medium.en", "medium", "large-v1", "large-v2", "large-v3", "distil-large-v3"}`. Validate `model_size` against this set; if invalid, log a WARNING and fall back to `"tiny.en"`.
- **Test:** Call `STTEngine(model_size="../../../etc/passwd")` and assert it falls back to "tiny.en" with a WARNING log. Call with valid sizes (`tiny`, `medium.en`, `large-v3`) and assert they pass through unchanged. Call with `"not-a-real-model"` and assert fallback.

### 4.6 LOW-7 — `xdg-open` on LLM-controlled path

- **Original review:** "Clicking an image in a chat bubble calls `_open_in_viewer(file_path)` which uses `shutil.which('xdg-open')` to open the file. If the LLM produces a `file://` or shell-special path, this could be exploited."
- **HEAD reality (`ui/views/chat_bubble.py:50-58`):** `_open_in_viewer(file_path)` is called from `_build_image_block` (line 412). It only runs if `os.path.isfile(file_path)` returns True (line 53), so a non-existent file is already filtered. However, the `file_path` could be an absolute path on the system that the LLM chose (e.g., `/home/q/.ssh/id_rsa` — unlikely but possible). The `subprocess.Popen([opener, file_path])` call is a vector if the opener is something unexpected.
- **Fix:** Add a project-scope check: only open files that are inside the current project path (passed via env var or constructor), or inside the user's home, or inside `/tmp` (whitelisted). Refuse to open paths that resolve via symlinks to outside the whitelist. Use a `Gtk.FileLauncher` (Gtk 4.10+) if available, falling back to `xdg-open` with the path constraint.
- **Test:** Call `_open_in_viewer("/etc/passwd")` and assert it does NOT call subprocess. Call with a path inside a project dir and assert it opens. Mock the subprocess and assert the command is sanitized.

### 4.7 LOW-8 — Unescaped SVG interpolation

- **Original review:** "`utils/icons.py` interpolates `color_hex` directly into SVG strings without escaping. A malicious `color_hex` value (e.g., `'#6366f1"/></path><script>alert(1)</script><path fill="`) could inject SVG content."
- **HEAD reality (`utils/icons.py:84-85, 150, 159`):** `fill="{color_hex}"` and `letter-spacing="0">{initials}</text>` — `color_hex` and `initials` are interpolated without HTML/XML escaping. Currently, callers pass hex strings (`#6366f1`) and ASCII initials, so no exploit is possible in practice. But the code does not enforce this — if a future caller passes user-controlled `initials` (the LLM could pick an agent name with malicious chars), the SVG is unsafe.
- **Fix:** (a) Add a `_escape_svg_attr(value: str) -> str` helper that escapes `&`, `<`, `>`, `"`, `'`. (b) Add a `_validate_color_hex(value: str) -> str` helper that ensures the value matches `^#[0-9a-fA-F]{3,8}$` — reject anything else with a fallback to a safe default. (c) Add a `_validate_initials(value: str) -> str` helper that keeps only alphanumerics (max 2 chars). (d) Use these helpers in both `render_folder_icon` and `render_agent_icon`.
- **Test:** Call `render_agent_icon("#6366f1</path><script>alert(1)</script><path fill=", "Qr")` and assert the result is `None` or uses a fallback. Call with `initials='<script>'` and assert they are stripped. Call with valid inputs and assert the output texture is non-None.

### 4.8 LOW-9 — Raw `str(e)` from GitPython leaks

- **Original review:** "`utils/git_ops.py` returns `error=str(e)` from GitPython exceptions, which can include partial stdout, system paths, or stack-trace fragments. A diff that touches `.git/` or a protected path could leak that information into the UI."
- **HEAD reality (`utils/git_ops.py:42, 55, 66, 77, 115, 126, 136, 146, 162, 172, 192, 207, 224, 234`):** 14 `error=str(e)` sites in git_ops.py. Plus `utils/provider_test.py:245` and `utils/mcp_client.py:273`. GitPython exceptions can be verbose — `git.exc.GitCommandError` includes the command, partial stdout, and partial stderr.
- **Fix:** Introduce a `_safe_error(e: Exception, *, max_len: int = 200) -> str` helper in `utils/git_ops.py` that:
  - extracts only the exception class name and a sanitized message
  - strips absolute paths (replaces `/home/q/...` with `~`, `C:\...` with `...`)
  - truncates to `max_len` chars
  - never includes the full repr/args of the exception
  Apply at all 14 sites. Add similar treatment in `provider_test.py:245` and `mcp_client.py:273`.
- **Test:** Construct a fake `GitCommandError` with a long message containing `/home/user/secret/file`, call `_safe_error(e)`, and assert the result is truncated, the path is replaced with `~`, and the result is ≤ 200 chars.

### 4.9 LOW-10 — `lstrip("a/")` character-set bug

- **Original review:** "`parts[2].lstrip('a/')` strips any combination of the characters `a` and `/` from the left, not the prefix `a/`. A file named `apple.py` would be incorrectly stripped to `pple.py`."
- **HEAD reality (`utils/diff_parser.py:149-150, 211-212, 226-227`):** Three sites use `lstrip("a/")` or `lstrip("b/")`. The bug: a file `apple.py` matched by the regex `diff --git a/apple.py b/apple.py` would have its old_path computed as `parts[2].lstrip("a/")` = `pple.py` (the leading `a` is stripped, but so is the `/` and then the next `p`... wait, actually `lstrip` strips any *combination* of the chars in the arg, so `lstrip("a/")` strips leading chars that are in `{'a','/'}`. For `"a/apple.py"` → strips `a/`, leaves `apple.py`. For `"a/pple.py"` (if that ever appeared) → strips `a/`, leaves `pple.py`. The bug is more subtle: `lstrip` with a char-set is the wrong tool for stripping a *prefix*. A file literally named `"afoo.txt"` matched by the same regex would become `foo.txt` (the leading `a` is incorrectly stripped).
- **Fix:** Replace `lstrip("a/")` and `lstrip("b/")` with a `removeprefix("a/")` and `removeprefix("b/")` (Python 3.9+). Add a 3-character check (the prefix is exactly 2 chars: `a/`, plus the path must start with that).
- **Test:** Feed `parse_diff` a diff with `diff --git a/apple.py b/apple.py` and assert `old_path == "apple.py"` (not `pple.py` or `ple.py`). Feed `diff --git a/ab.txt b/ab.txt` and assert `old_path == "ab.txt"`. Feed `diff --git a/afile.txt b/afile.txt` and assert old_path is `afile.txt`, not stripped.

### 4.10 LOW-11 — `load_agent_defs` doesn't validate

- **Original review:** "`load_agent_defs()` parses YAML/JSON but does not run `validate_agent_def`. A malformed agent def (unknown tool, missing prompt file, unknown provider) loads silently and the runtime crashes on first use."
- **HEAD reality (`utils/agent_defs.py:190, 345`):** `load_agent_defs()` parses but does not call `validate_agent_def`. `validate_agent_def` exists and is callable, but is not invoked at load time.
- **Fix:** Call `validate_agent_def(agent_def)` inside `load_agent_defs()` after each successful parse. If validation returns errors, log a WARNING with the agent name and the errors, and skip the def (do not include in the returned list). The `validate_agent_def` is already pure, no side effects — safe to call here.
- **Test:** Write an agent def with an unknown tool name to the agents dir. Call `load_agent_defs()` and assert the invalid def is NOT in the result. Assert a WARNING is logged. Call with a valid def and assert it IS in the result.

### 4.11 LOW-12 — `.crabcakes/feed.json` not auto-gitignored

- **Original review:** "When a project feed is saved, `.crabcakes/feed.json` lands in the working tree but is not added to `.gitignore`. The user accidentally commits the feed and pollutes the git history."
- **HEAD reality (`utils/feed_store.py:122-128`):** `save_feed` writes to `.crabcakes/feed.json` but does not touch `.gitignore`. `append_feed_card` and `update_feed_card` have the same issue.
- **Fix:** Add a `_ensure_gitignore_entry(project_path, entry)` helper in `utils/feed_store.py` that:
  - checks if `project_path/.gitignore` exists; if not, creates it
  - reads the file, checks if `entry` is already present (handling trailing comments)
  - if not, appends `entry` on its own line
  - called from `save_feed`, `append_feed_card`, and `update_feed_card` with the entry being `.crabcakes/feed.json`
  - writes are atomic (`.tmp` + `os.replace` + `chmod 0o644` to match gitignore convention)
- **Test:** Call `save_feed` on a project with no `.gitignore` and assert `.gitignore` is created with `.crabcakes/feed.json` in it. Call again and assert the file is unchanged. Call on a project that already has `.gitignore` with the entry, assert no duplicate.

### 4.12 LOW-13 — `save_feed` is non-atomic

- **Original review:** "`save_feed` writes `feed.json` directly. A crash mid-write corrupts the file and the user loses the entire feed history."
- **HEAD reality (`utils/feed_store.py:122-128`):** `save_feed` opens the file for writing and calls `json.dump`. No `.tmp` + `os.replace` pattern. The reference pattern is at `agent/runtime.py:1063-1066` (`tmp = path + ".tmp"; open(tmp, "w"); os.replace(tmp, path)`).
- **Fix:** Refactor `save_feed` to use the atomic pattern: write to `path + ".tmp"`, then `os.replace(tmp, path)`. Set permissions to `0o600` (matches the security pattern in `runtime.py:1069-1072`). Note: the existing `append_feed_card` and `update_feed_card` already use `with open(path, "w")` directly — they have the same bug and need the same fix.
- **Test:** Call `save_feed` and assert that during the write window, the file `feed.json.tmp` exists and `feed.json` either does not exist or contains the previous valid content. Call `append_feed_card` and assert the same atomicity. (Use a monkey-patched `json.dump` that raises mid-write to simulate a crash, then assert `feed.json` is still valid.)

### 4.13 A-10 — Dead code cleanup

- **Original review:** Four sub-items; only the ones still present on HEAD are in scope.

| Sub-item | HEAD reality | Fix |
|---|---|---|
| `utils/image_utils.py` has zero importers | Confirmed: no `import` of `image_utils` anywhere | Delete `utils/image_utils.py` |
| `left_panel.py:13` unused `PromptsHandler` import | Already fixed in current code — the import is no longer there | **No-op — out of scope** |
| `review_log.py:19` references nonexistent `agent/dream_engine` | Confirmed: line 19 comment says "Shared with agent/dream_engine.py" but no such file exists | Remove the `agent/dream_engine.py` reference from the comment. Keep `DREAM_LOG_FILENAME` constant (it's used) |
| `feed_handler.py` duplicate `Remove` column header | No duplicate `Remove` header found in current code | **No-op — out of scope** |

- **Test:** Assert `image_utils.py` is deleted. Assert `review_log.py:19` no longer mentions `dream_engine.py`. Assert all existing tests still pass.

## 5. Spec coverage of the original review

| Original review ID | Title | In this spec? | Fix target |
|---|---|---|---|
| LOW-2 | File tools default sandbox to `/tmp` | ✅ | §4.1 |
| LOW-3 | `operator.admin` scope constructor param | ✅ | §4.2 |
| LOW-4 | Raw gateway log dump | ✅ (re-scoped) | §4.3 |
| LOW-5 | Unvalidated event payloads | ✅ | §4.4 |
| LOW-6 | STT manifest/network/model-size claim | ✅ | §4.5 |
| LOW-7 | `xdg-open` on LLM-controlled path | ✅ | §4.6 |
| LOW-8 | Unescaped SVG interpolation | ✅ | §4.7 |
| LOW-9 | Raw `str(e)` from GitPython leaks | ✅ | §4.8 |
| LOW-10 | `lstrip("a/")` character-set bug | ✅ | §4.9 |
| LOW-11 | `load_agent_defs` doesn't validate | ✅ | §4.10 |
| LOW-12 | `.crabcakes/feed.json` not auto-gitignored | ✅ | §4.11 |
| LOW-13 | `save_feed` non-atomic | ✅ | §4.12 |
| A-10 | Dead code cleanup | ✅ (1 of 4 sub-items still applicable) | §4.13 |
| Other LOW/A-* | (Already shipped in Phase 0–3, or in Phase 3 re-bucketed LOWs) | — | — |

**Total: 13 finding-touches (12 LOWs + 1 arch).** All match the original review's IDs.

## 6. Phasing — how the work is split

Per `implementationSupervisor.md` §2, each phase is **1-3 files** and **independently verifiable**. The 13 fixes touch 11 files. I will group them into 5 phases by *domain* (not by finding), so that within a phase, the changes are coherent and a single test sweep can verify them.

| Phase | Files | Findings | Why grouped |
|---|---|---|---|
| **Phase 1 — Runtime file sandbox** | `agent/runtime.py` (LOW-2) | LOW-2 | Self-contained; one test file |
| **Phase 2 — Gateway client hardening** | `gateway/client.py` (LOW-3, LOW-4, LOW-5) | LOW-3, LOW-4, LOW-5 | All in the same module; shared validation pattern |
| **Phase 3 — Utility hardening (stt, icons, diff_parser, agent_defs, git_ops)** | `utils/stt.py` (LOW-6), `utils/icons.py` (LOW-8), `utils/diff_parser.py` (LOW-10), `utils/agent_defs.py` (LOW-11), `utils/git_ops.py` (LOW-9), `utils/provider_test.py` (LOW-9), `utils/mcp_client.py` (LOW-9) | LOW-6, LOW-8, LOW-9, LOW-10, LOW-11 | All `utils/` pure-Python; single test sweep |
| **Phase 4 — Feed store + dead code** | `utils/feed_store.py` (LOW-12, LOW-13), `utils/image_utils.py` (delete, A-10), `utils/review_log.py` (A-10 comment) | LOW-12, LOW-13, A-10 | feed_store is one file; A-10 items are small |
| **Phase 5 — UI image viewer hardening** | `ui/views/chat_bubble.py` (LOW-7) | LOW-7 | UI module; one test |

Each phase-instructions file (`docs/specs/SECURITY-PHASE4-{1..5}-INSTRUCTIONS.md`) will be created *before* the first `/ask` of that phase, with the exact edits, file:line references, and COMPLETENESS checklist.

## 7. Acceptance criteria

The loop is done when **all** of the following are true:

- [ ] All 13 finding-touches (§4) are addressed in the code
- [ ] Every new behavior has at least one test that fails without the fix and passes with it
- [ ] `pytest tests/ -x --ignore=tests/test_agent_runtime.py` passes (the `test_agent_runtime.py` hang is pre-existing and out of scope — see §8)
- [ ] `git log --oneline -5` shows 5 commit messages, one per phase, each prefixed with `fix(security):` or `chore(security):` as appropriate
- [ ] `git grep` confirms the 12 unshipped patterns are gone (e.g., `git grep "or \"/tmp\"" agent/runtime.py` returns 0 lines)
- [ ] A `docs/post-mortems/2026-06-19-SECURITY-REMEDIATION-PHASE-4-POST-MORTEM.md` exists matching the §6 format from `implementationLoop.md`
- [ ] The post-mortem contains a per-finding table mapping each of the 12 LOWs and A-10 sub-item to the commit SHA that shipped it
- [ ] All commits are pushed to `origin/main`

## 8. Pre-existing issues (out of scope)

These are present on HEAD before this loop starts and are **not** addressed in this loop:

- `tests/test_agent_runtime.py` hangs at 30/66 tests on clean HEAD (timeout). Pre-existing, unrelated to security remediation. Not in scope per the scope-creep rule.
- The post-mortem template path: this is a metadata issue (`ARCHITECTURE.md` says `docs/post-mortems/` is the convention; `docs/audits/` and `docs/specs/` are not separately defined). The supervisor will follow `implementationLoop.md` §6.4 and use the post-mortem convention, not create new audit doc dirs.

## 9. Open questions for the captain

None. The spec is self-contained: every fix is grounded in the original review's wording, the HEAD code, and the steelFramedCodeWriter / adversarialDebugger rules. The captain approves by saying "proceed."

## 10. References

- Original review: `docs/SECURITY_ARCHITECTURE_REVIEW.md` (commit `ca24246`)
- Phase 3 spec that drifted: `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md`
- Post-mortem: `docs/post-mortems/2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md`
- Authority floor: `docs/ARCHITECTURE.md`
- Prompt set used: `prompts/steelFramedSpecWriter.md`, `prompts/steelFramedCodeWriter.md`, `prompts/implementationSupervisor.md`, `prompts/implementationLoop.md`, `prompts/adversarialDebugger.md`

---

**End of spec. Loop may begin once this is on disk and the captain has acknowledged.**
