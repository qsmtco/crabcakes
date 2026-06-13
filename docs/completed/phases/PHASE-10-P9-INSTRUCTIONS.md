# PHASE 10 — P9: ARCHITECTURE.md §12 update

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST, §8)
**Phase scope:** Section 8 of the master spec

---

## Files to change

1. `docs/ARCHITECTURE.md` — insert new §12 "Provider Resolution & API Caller", renumber old §12→§13, old §13→§14

## What to do

**IMPORTANT:** The spec references "§12 Provider Resolution & API Caller" but the current ARCHITECTURE.md has §12 as "File Inventory". This means the spec was written assuming §12 would be this section. The cleanest fix is to:

1. Insert a new section "12. Provider Resolution & API Caller" BEFORE the current §12 "File Inventory"
2. Renumber the old §12 "File Inventory" → §13
3. Renumber the old §13 "Principles to Preserve" → §14
4. Add the paragraph from the spec
5. Add a cross-reference in §2.7 "Single Source of Truth"

**Edit 1 — Find the current §12 heading and insert the new section before it:**

Find in `docs/ARCHITECTURE.md` (around line 3037):
```markdown
## 12. File Inventory
```

Insert BEFORE it (new §12):
```markdown
## 12. Provider Resolution & API Caller

As of PHASE-10, the API caller for a provider is resolved via `provider_cfg.caller`, a per-provider attribute persisted in `providers.yaml`. The runtime's `_resolve_caller_key(provider_cfg, model)` helper returns the explicit `caller` if set, otherwise derives it from `provider_cfg.default_model.split("/")[0]`, and finally falls back to `model.split("/")[0]`. This decouples the model-string prefix structure (which is the API's contract — e.g. `openrouter/owl-alpha` for OpenRouter) from the caller's identity (which is one of the five built-in implementations: `openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

**Resolution priority** (highest to lowest):
1. `provider_cfg.caller` (explicit, lowercased)
2. `provider_cfg.default_model.split("/")[0]` (derivation from configured model)
3. `model.split("/")[0]` (legacy fallback for callers without a `ProviderConfig`)

**Why explicit caller + derivation:** existing providers in `providers.yaml` (pre-PHASE-10) don't have a `caller` field. The derivation fallback (`default_model.split("/")[0]`) handles migration transparently — all 6 of the user's existing providers have slashed `default_model` values, so the runtime resolves the correct caller without requiring a re-save.

**Why the model string is still slashed:** the API caller functions receive the model string verbatim. OpenRouter expects `vendor/model` (e.g. `openrouter/owl-alpha`); Anthropic expects a bare model name (e.g. `claude-3-5-sonnet`); OpenAI expects a bare model name. The slash in the model string is the API's contract, not a caller identifier. The runtime's `_resolve_agent_model` handler (P4) preserves the model string exactly as configured when `default_model` contains a slash.

**Streamer resolution:** the streaming path (`_call_llm_streaming` callers) uses the same `_resolve_caller_key` helper to look up the streamer function in `_PROVIDER_STREAMERS`. The streamer keys mirror the caller keys (`openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

**Test Connection:** the Settings dialog's "Test" button calls `test_connection(base_url, api_key, model, caller=provider.caller)`. The `caller` kwarg (added in PHASE-10) overrides the legacy model-prefix derivation so the test uses the same caller the runtime would use at message-send time.

```

**Edit 2 — Renumber old §12 → §13:**

Find:
```markdown
## 12. File Inventory
```

Replace with:
```markdown
## 13. File Inventory
```

**Edit 3 — Renumber old §13 → §14:**

Find:
```markdown
## 13. Principles to Preserve
```

Replace with:
```markdown
## 14. Principles to Preserve
```

**Edit 4 — Update §2.7 "Single Source of Truth" (if it exists):**

Find the section header for §2.7. If it exists, add a bullet point:

```markdown
- The `caller` value is a per-provider attribute (persisted in `providers.yaml` as `caller:`), not a per-model-segment derived value. The runtime's `_resolve_caller_key` helper resolves the caller with explicit > derivation > fallback priority.
```

If §2.7 doesn't exist or doesn't have a bullet list, skip this edit.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `docs/ARCHITECTURE.md` lines 3030-3260 COMPLETELY before editing
- Read `docs/ARCHITECTURE.md` lines 60-200 to find §2.7 before editing
- Make ONLY the 4 edits described above
- Do NOT touch any other section numbers or content
- Do NOT reformat the existing File Inventory section (just renumber the heading)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
grep -n "^## 12\|^## 13\|^## 14" docs/ARCHITECTURE.md
```

Expect:
```
LINE:## 12. Provider Resolution & API Caller
LINE:## 13. File Inventory
LINE:## 14. Principles to Preserve
```

```bash
cd /home/q/projects/crabcakes
grep -n "_resolve_caller_key\|provider_cfg.caller\|caller.*per-provider" docs/ARCHITECTURE.md
```

Expect: at least 3 matches showing the new content is in place.

```bash
cd /home/q/projects/crabcakes
# Verify §2.7 has the new bullet (or that §2.7 doesn't exist and we skipped)
grep -n "## 2.7" docs/ARCHITECTURE.md
```

If the line exists, verify the bullet was added:
```bash
cd /home/q/projects/crabcakes
grep -A 5 "## 2.7" docs/ARCHITECTURE.md | head -10
```

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.