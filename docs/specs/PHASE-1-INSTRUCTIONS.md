# PHASE 1 of 9 — Data Layer (Providers)

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.1, §2.2, §2.3 (with §2.15 tests)

## Files to create (4 files)

1. `models/providers.py` — pure dataclass
2. `utils/providers_store.py` — YAML persistence
3. `utils/provider_test.py` — Test Connection network probe
4. `tests/test_providers_store.py` + `tests/test_provider_test.py` — tests

## Hard rules — read these first

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow it exactly. No deviation.
- **Operating from the authorized project channel** (crabcakes CLI). The standing trigger word `write` is included in this delegation.
- **No agents or runtime code in this phase** — pure data + I/O + network. No GTK, no `agent.*` imports, no `ui.*` imports.
- **Follow the `utils/feed_store.py` and `utils/agent_defs.py` patterns** — those are the closest precedents.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report. Format is mandatory. A response without it is INCOMPLETE.

## Discovery — read these files first

1. `models/conversation_snapshot.py` (or whatever model dataclass file exists in `models/`) — for the dataclass + manifest docstring pattern
2. `utils/feed_store.py` — pattern for the YAML store
3. `utils/agent_defs.py` lines 1-15 (imports), lines 60-103 (YAML parse with JSON fallback), lines 466-490 (`get_available_providers`)
4. `agent/runtime.py` lines 100-200 (provider HTTP callers — the format your `provider_test.py` must mirror)
5. `agent/runtime.py` lines 145-160 (MiniMax body-level error pattern — your `provider_test.py` MUST replicate this exactly for MiniMax)
6. `agent/runtime.py` lines 280-330 (Anthropic message format)
7. `tests/conftest.py` lines 14-23 (`tmp_config_dir` fixture)
8. `tests/test_agent_defs.py` lines 1-80 (test style: tmpdir + monkeypatch)

Output a DISCOVERY block listing each file read and what you learned.

## Edit 1: `models/providers.py` (NEW)

**Spec §2.1.** Pure dataclass. NO `app_title` field. NO GTK. NO `dataclasses.field(default_factory=...)` for anything fancy.

```python
# models/providers.py
# Manifest:
#   - Reads: nothing
#   - Writes: nothing
#   - Network: none
#   - Imports: only stdlib dataclasses

from dataclasses import dataclass

@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    default_model: str
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    last_verified_at: str | None = None
    last_error: str | None = None
```

**Files-ending-with-trailing-newline check:** run `tail -c 1 models/providers.py | xxd` after writing and confirm the last byte is `0a`.

## Edit 2: `utils/providers_store.py` (NEW)

**Spec §2.2.** Pure functions, no GTK, no logging beyond stdlib. Mirrors `utils/feed_store.py`.

Required public API (exact signatures):

```python
def get_providers_path() -> str: ...
def load_providers() -> list[ProviderConfig]: ...
def save_providers(providers: list[ProviderConfig]) -> None: ...
def add_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None: ...
def remove_provider(providers: list[ProviderConfig], name: str) -> None: ...
def update_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None: ...
def has_any_verified_provider(providers: list[ProviderConfig]) -> bool: ...
```

**Hard requirements:**
- YAML if `pyyaml` is importable, else JSON (same pattern as `utils/agent_defs.py:64-103`).
- `save_providers` writes to `path + ".tmp"` then `os.rename` — atomic write.
- `save_providers` calls `os.chmod(path, 0o600)` after the rename. Wrap in try/except for non-POSIX FS.
- `os.makedirs(parent, exist_ok=True)` on the parent dir; chmod `0o700` if it was just created.
- `get_providers_path` uses `from utils.config import get_config_dir` — do NOT duplicate the path logic.
- `load_providers` returns `[]` (not raises) on missing file, malformed YAML, or empty list.
- `load_providers` logs warnings on per-line parse failures (via stdlib `logging` with `getLogger(__name__)`).
- `has_any_verified_provider` returns `True` if ANY provider has `last_verified_at is not None`.

**Exception classes to consider catching:** `ImportError` (no pyyaml), `OSError` (file I/O), `yaml.YAMLError` if pyyaml is available.

**`add_provider` semantics:** if a provider with the same `name` already exists, replace it. The function reads existing, replaces, then calls `save_providers`.

**`remove_provider` semantics:** no-op (no error) if name not found. Loads, filters, saves.

**`update_provider` semantics:** same as `add_provider` — replace by name.

## Edit 3: `utils/provider_test.py` (NEW)

**Spec §2.3.** Network probe. NO `agent.*` imports (avoid bringing in the runtime). Use stdlib `urllib`.

Required public API:

```python
@dataclass
class TestResult:
    ok: bool
    latency_ms: int
    error: str | None
    model_used: str

def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
) -> TestResult: ...
```

**Hard requirements — replicate the runtime's behavior exactly:**

1. **Provider detection:** `model.split("/")[0]` if `/` in model, else the whole `model` string.
2. **OpenAI-compatible branch** (provider in `{"openai", "openrouter", "zai", "minimax"}`):
   - POST `{base_url.rstrip('/')}/chat/completions`
   - Body: `{"model": <bare_id>, "messages": [{"role":"user","content":"hi"}], "max_tokens": 1}`
   - Headers: `Content-Type: application/json`, `Authorization: Bearer <api_key>`
   - **No `HTTP-Referer` or `X-Title` headers** — those are agent-level (app_title), not provider-level. Your function does not take an `app_title` parameter.
3. **Anthropic branch** (provider == `"anthropic"`):
   - POST `{base_url.rstrip('/')}/messages`
   - Body: `{"model": <bare_id>, "messages": [{"role":"user","content":"hi"}], "max_tokens": 1}`
   - Headers: `Content-Type: application/json`, `x-api-key: <api_key>`, `anthropic-version: 2023-06-01`
4. **Unknown provider:** raise `ValueError(f"No adapter for provider: {provider_name}")`.
5. **MiniMax body-level error handling (CRITICAL):** after a 2xx response, parse the JSON body and check `base_resp.status_code != 0`. If set, return `TestResult(ok=False, error=f"status_code={n}: {msg}", latency_ms=elapsed, model_used=model)`. Mirror `agent/runtime.py:145-160`.
6. **HTTP error handling:** catch `urllib.error.HTTPError`, read body, return `TestResult(ok=False, error=f"HTTP {code}: {body[:200]}", ...)`. Do NOT raise.
7. **Other exceptions** (network timeout, DNS failure, JSON decode): catch, return `TestResult(ok=False, error=str(exc)[:200], ...)`. Do NOT raise.
8. **Latency:** measure from request start to response read complete with `time.monotonic()`.

## Edit 4: `tests/test_providers_store.py` (NEW)

Use `tmp_config_dir` from `tests/conftest.py:14-23` (monkeypatches HOME).

Required test classes:
- `TestGetProvidersPath` — returns path under `~/.config/crabcakes/`, contains `providers.yaml` filename.
- `TestLoadSave`:
  - `test_round_trip_yaml` — write 2 providers, load, assert exact match
  - `test_round_trip_json_fallback` — if pyyaml is missing, skip with `pytest.skip`; else write a JSON file and confirm load works
  - `test_missing_file_returns_empty` — load on non-existent file → `[]`
  - `test_malformed_yaml_returns_empty` — write garbage, load → `[]`, no exception
  - `test_atomic_write_no_partial_on_failure` — simulate a failure mid-save (mock `yaml.dump` to raise) and confirm no `.tmp` file is left behind
- `TestFilePermissions`:
  - `test_save_sets_mode_0o600` — after `save_providers`, `os.stat(path).st_mode & 0o777 == 0o600`
  - `test_parent_dir_mode_0o700_on_create` — when the parent dir doesn't exist, after `save_providers` it should be `0o700`
- `TestAddUpdateRemove`:
  - `test_add_new` — `add_provider(list, p)` on empty list → list has 1
  - `test_add_replaces_existing_by_name` — add p1, then add p1' with same name → list has 1 (p1')
  - `test_remove_existing` — remove by name → list empty
  - `test_remove_nonexistent_is_noop` — remove on missing name → no exception
  - `test_update_existing` — update with same name → replaced
  - `test_update_new_appends` — update on missing name → appended
- `TestHasAnyVerifiedProvider`:
  - `test_empty_list_false`
  - `test_all_unverified_false` — all `last_verified_at is None`
  - `test_one_verified_true` — at least one has `last_verified_at` set
  - `test_ignores_last_error` — a provider with `last_error="X"` but `last_verified_at=None` does NOT count

## Edit 5: `tests/test_provider_test.py` (NEW)

**Mock at the boundary** — patch `urllib.request.urlopen` (or wherever the test code does HTTP). Do NOT mock the function being tested.

Required test classes (mirror the actual behavior, not just the interface):
- `TestOpenAICompatible`:
  - `test_success_returns_ok` — stub urlopen to return 200 with `{"choices": [{"message": {"content": "hi"}}]}`, no `base_resp` → `ok=True`, `latency_ms >= 0`
  - `test_401_returns_fail_with_body` — raise `HTTPError(401, ...)` with body "invalid key" → `ok=False, error contains "401", error contains "invalid key"`
  - `test_request_uses_correct_url` — assert urlopen was called with `https://api.example.com/v1/chat/completions` (verify the `rstrip('/')` works on a URL with trailing slash)
  - `test_request_uses_correct_bearer_header` — assert `Authorization: Bearer sk-xxx` in the request
  - `test_request_strips_provider_prefix_from_model` — pass `model="openrouter/qwen/qwen3.7-max"` → body has `model == "qwen/qwen3.7-max"`
- `TestMinimaxBodyLevelError` (CRITICAL — this catches the original failure mode):
  - `test_body_status_code_nonzero_returns_fail` — stub urlopen to return 200 with `{"base_resp": {"status_code": 1004, "status_msg": "login fail..."}, "choices": []}` → `ok=False, error contains "1004", error contains "login fail"`
  - `test_body_status_code_zero_returns_ok` — stub returns 200 with `base_resp.status_code == 0` and a valid choice → `ok=True`
  - `test_body_missing_base_resp_returns_ok` — stub returns 200 with no `base_resp` field → `ok=True` (defensive: do not assume field exists)
- `TestAnthropic`:
  - `test_success_returns_ok` — stub 200 with `{"content": [{"type": "text", "text": "hi"}]}` → `ok=True`
  - `test_request_uses_x_api_key_not_bearer` — assert header `x-api-key: sk-ant-xxx` (not `Authorization: Bearer`)
  - `test_request_uses_anthropic_version` — assert `anthropic-version: 2023-06-01`
- `TestNetworkErrors`:
  - `test_timeout_returns_fail` — patch urlopen to raise `socket.timeout` (or `TimeoutError`) → `ok=False, error contains "timeout"`
  - `test_dns_failure_returns_fail` — raise `urllib.error.URLError("Name or service not known")` → `ok=False`
  - `test_malformed_json_returns_fail` — stub 200 with non-JSON body → `ok=False`
- `TestUnknownProvider`:
  - `test_raises_value_error` — pass `model="unknown-vendor/foo"` (where `unknown-vendor` is not in the supported list) → raises `ValueError` containing "No adapter" or "Unknown provider"

## Verification commands (you MUST run and paste output)

```bash
cd /home/q/projects/crabcakes

# 1. Files exist
ls -la models/providers.py utils/providers_store.py utils/provider_test.py tests/test_providers_store.py tests/test_provider_test.py

# 2. All four files end with trailing newline
for f in models/providers.py utils/providers_store.py utils/provider_test.py tests/test_providers_store.py tests/test_provider_test.py; do
  echo -n "$f: "
  tail -c 1 "$f" | xxd
done

# 3. Compile check
python3 -m py_compile models/providers.py utils/providers_store.py utils/provider_test.py
echo "compile exit: $?"

# 4. New tests pass
python3 -m pytest tests/test_providers_store.py tests/test_provider_test.py -v --tb=short 2>&1 | tail -80

# 5. Existing tests still pass (regression check)
python3 -m pytest tests/test_agent_defs.py tests/test_config.py -q --tb=short 2>&1 | tail -20

# 6. No new code imports from agent.* or ui.* (verify data layer purity)
grep -E "^(from|import) (agent|ui)" models/providers.py utils/providers_store.py utils/provider_test.py && echo "VIOLATION" || echo "clean"

# 7. providers_store uses atomic write (grep for .tmp + rename pattern)
grep -n "\.tmp\|os.rename" utils/providers_store.py

# 8. provider_test handles MiniMax body-level error (grep for base_resp)
grep -n "base_resp" utils/provider_test.py

# 9. Save uses chmod 0o600
grep -n "chmod.*0o600\|chmod.*0o700" utils/providers_store.py
```

## Acceptance criteria for this phase

- [ ] All 4 source files created, all end with trailing newline
- [ ] `python3 -m py_compile` passes on all 4
- [ ] `pytest tests/test_providers_store.py tests/test_provider_test.py` — 100% pass, sad-path ≥30%
- [ ] `pytest tests/test_agent_defs.py tests/test_config.py` — 100% pass (no regression)
- [ ] No imports of `agent.*` or `ui.*` in the 3 source files
- [ ] Atomic write pattern in `save_providers`
- [ ] `chmod 0o600` on save, `chmod 0o700` on parent dir creation
- [ ] MiniMax body-level error handling in `test_connection` (grep proof)
- [ ] **COMPLETENESS block** at end of report (see format below)

## Report format

After completing the work, reply with:

```
PHASE 1 of 9 — COMPLETE

Files created:
- models/providers.py — N lines (run wc -l and paste)
- utils/providers_store.py — N lines
- utils/provider_test.py — N lines
- tests/test_providers_store.py — N lines
- tests/test_provider_test.py — N lines

Test results:
[paste full pytest output for the new test files, last 80 lines]

Regression check:
[paste last 20 lines of test_agent_defs.py + test_config.py run]

Verification commands:
[paste outputs of commands 6, 7, 8, 9 from above]

**COMPLETENESS:**
- [x] Edit 1: models/providers.py — evidence: <line N where dataclass lives, grep output>
- [x] Edit 2: utils/providers_store.py — evidence: <line N where each public function lives>
- [x] Edit 3: utils/provider_test.py — evidence: <line N where MiniMax body-level check lives>
- [x] Edit 4: tests/test_providers_store.py — evidence: <test count, all pass>
- [x] Edit 5: tests/test_provider_test.py — evidence: <test count, all pass, MiniMax body-level test included>

**Related issues found — not fixed in this phase:**
- (none, or list)

**Implementation choices made:**
- (none, or list with one-sentence rationale each)
```

When done, please write a final line: `Phase 1 complete — ready for audit.`
