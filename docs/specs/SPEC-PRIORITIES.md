# Spec Priorities — Open Items

**Date:** 2026-06-12
**Author:** QTR
**Context:** After full audit of all 113 spec files against the codebase. 22 DONE, 2 PARTIAL, 1 SUPERSEDED, 2 PENDING.

---

## Priority 1 — Telegram Remote Input (PENDING)

**File:** `docs/specs/SPEC_TELEGRAM_REMOTE_INPUT.md`
**Effort:** ~1 day
**Impact:** High — solves a real daily pain (dictate on phone, edit on desktop)
**Risk:** Low — standalone feature, zero dependencies
**Status:** Spec is thorough. Discovery done, architecture mapped, follows the STT pattern (`utils/stt.py`). Long polling Telegram Bot API client in a background thread, inserts text at cursor via `GLib.idle_add()`. Config in `~/.config/crabcakes/config.json`.

Why first: The Captain asked for this directly. It's the most impactful pending feature with the clearest path to completion. No other work depends on it.

---

## Priority 2 — Agent-to-Agent Comms completion (PARTIAL)

**File:** `docs/specs/SPEC-agent-to-agent-comms.md`
**Effort:** ~2-3 days
**Impact:** High — unlocks multi-agent collaboration in project tabs
**Risk:** Medium — crosses transport layers (gateway agents vs special agents)
**What's done:** Mention resolution (`_resolve_mention()` in `command_handler.py:482` now resolves special agents). Response routing (`_relay_response()` in `agent_command_handler.py:347`). The `/ask @Agent` syntax is wired in the CLI.
**What's missing:** Ephemeral relay thread system, convergence detection (knowing when an A2A exchange is complete), thread identity across transport layers (gateway ↔ special agent).

Why second: The foundation is in place. Completing this means Coder can ask QTR a question and get a routed response in the same project tab. This is the key to multi-agent workflows.

---

## Priority 3 — Per-Agent API Key (PENDING → recommend REJECTED)

**File:** `docs/specs/SPEC_PER_AGENT_API_KEY.md`
**Effort:** ~1 day if pursued
**Impact:** Low
**Status:** The codebase explicitly rejected this design. `SpecialAgentDef` still uses flat `api_key: str | None`. Test `test_agent_builder_no_provider_keys.py` asserts `provider_keys` is NOT required. The single-key-per-agent design was a deliberate choice.

Recommendation: Mark as REJECTED rather than implement. The current `api_key` field with provider dropdown is sufficient. Unless the Captain has changed their mind.

---

## Priority 4 — Dream Consolidation (PARTIAL → waiting for data)

**File:** `docs/specs/SPEC-4-dream-consolidation.md`
**Effort:** ~1 day prototype, ongoing refinement
**Impact:** Unknown — experimental
**Risk:** High — most experimental feature, depends on accumulated data
**What's done:** Data infrastructure — `dream_consolidation` field in `utils/agent_defs.py:168` (defaults False). `utils/review_log.py` has `get_dream_log_path()` and `get_last_dream_timestamp()` helpers.
**What's missing:** The actual autonomous dream engine (`agent/dream_engine.py` or similar) that synthesizes feedback from SPECs 1-3 into prompt improvements.

Why last: The spec itself says "should not be implemented until SPECs 1-3 have been running for at least a week and have accumulated meaningful data." We need review data first. Revisit after 1-2 weeks of active multi-agent use.

---

## Already handled

- **Activity Bubble UX** (SUPERSEDED) — replaced by `SPEC-activity-drawer.md`. No work needed.
- **Chat Input Toolbar** (DONE) — all 10 phases shipped. Frontmatter tagged `status: DONE`.

---

## Summary table

| # | Spec | Status | Effort | Impact | Action |
|---|------|--------|--------|--------|--------|
| 1 | Telegram Remote Input | PENDING | 1 day | High | Implement next |
| 2 | Agent-to-Agent Comms | PARTIAL | 2-3 days | High | Implement after #1 |
| 3 | Per-Agent API Key | PENDING | — | Low | Mark REJECTED |
| 4 | Dream Consolidation | PARTIAL | 1+ day | Unknown | Wait for data |
| 5 | Activity Bubble UX | SUPERSEDED | — | — | No action needed |
